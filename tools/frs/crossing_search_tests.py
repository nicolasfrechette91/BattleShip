#!/usr/bin/env python3
"""Zero-tick tests of the crossing search (tools/frs/crossing_search.py). No game process is started: the real lab import and the real
frontier search outputs are read (never written) for the seed-rule and provenance checks; the synthetic stub world (rl/m8_rd_stub) stands
in for the game in the archive, selection, verification and end-to-end checks; the guard checks run in child processes (an audit hook
cannot be removed). The test process never arms the lab guard and writes only under temporary folders, which it removes.

    python -B tools/frs/crossing_search_tests.py                 every test
    python -B tools/frs/crossing_search_tests.py real            the real-import checks only (reads <lab root>/import and the frontier folder)
    python -B tools/frs/crossing_search_tests.py stub            the synthetic checks only
    python -B tools/frs/crossing_search_tests.py only <name>     the tests whose name contains <name>
    ... [--lab-root DIR] [--frontier DIR]                        the lab root and frontier folder of the real checks (default C:/BattleShip_lab, newest frontier_*)
"""
from __future__ import annotations

import json
import os
import random
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

import crossing_search as cs  # noqa: E402
import frontier_search as fs  # noqa: E402
import frontier_search_tests as fst  # noqa: E402
import frs_archive as fa  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_tests as T  # noqa: E402
import frs_verify as fv  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_stub as stub  # noqa: E402

# The owner's expectations from the frontier record (docs/frs_frontier_2026-10-14.md) on the sd2 import: test literals only, never read by the search.
EXPECTED_DEEPEST_BURST_LEVEL = 7
EXPECTED_POOL_KEYS = {"7": 21, "6": 145}
EXPECTED_SEEDS_PER_LEVEL = {"7": 21, "6": 27}
EXPECTED_TOP = (493, 846)                      # the fastest level-7 state: tick, lead
EXPECTED_BOUND = 1885 - 24 - 1                 # E7: the reference minus the registered margin minus one

TESTS: List[Tuple[str, str, Callable[[], Optional[Dict[str, Any]]]]] = []
CREATED: List[Path] = []
LAB = Path(g.DEFAULT_LAB_ROOT)
FRONTIER: Optional[Path] = None
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
    p = Path(tempfile.mkdtemp(prefix=f"crossing_{tag}_"))
    CREATED.append(p)
    return p


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def real_plan() -> Dict[str, Any]:
    """The real import and the real frontier outputs, planned once per test session (read-only)."""
    if not _REAL:
        imp = LAB / "import"
        check((imp / "import_manifest.json").is_file(), f"no lab import at {imp}")
        fd = FRONTIER or cs.default_frontier(LAB)
        check(fd is not None, f"no frontier search output folder under {LAB}")
        _REAL.update(cs.build_search_plan(LAB, fd, cs.Params()))
        _REAL["frontier_dir"] = fd
    return _REAL


# =============================================================================================================================================
# the real import and the real frontier outputs (zero native ticks)
# =============================================================================================================================================


@real
def real_seed_rule_on_frontier_outputs() -> Dict[str, Any]:
    P = real_plan()
    p, seeds, R, F, bound = P["plan"], P["seeds"], P["R"], P["F"], P["bound"]
    arrival = {int(k): int(v) for k, v in R["arrival"].items()}
    sr = p["seed_rule"]
    check(bound == EXPECTED_BOUND == p["e7"]["bound_max_L"] and p["e7"]["margin"] == 24, f"the E7 bound {bound}, expected {EXPECTED_BOUND}")
    check(sr["deepest_burst_level"] == EXPECTED_DEEPEST_BURST_LEVEL and sr["levels"] == [7, 6], f"the seed rule's levels {sr}")
    check({lv: d["keys"] for lv, d in sr["per_level_pool"].items()} == EXPECTED_POOL_KEYS, f"pool keys per level {sr['per_level_pool']}")
    check(p["seeds"] == len(seeds) == cs.Params.seeds and {lv: d["seeds"] for lv, d in p["per_level"].items()} == EXPECTED_SEEDS_PER_LEVEL,
          f"{p['seeds']} seeds, per level {p['per_level']}")
    check((seeds[0]["tick"], seeds[0]["lead"]) == EXPECTED_TOP and seeds[0]["level"] == 7, f"the top seed {seeds[0]['tick']} / {seeds[0]['lead']}")
    for s in seeds:
        check(len(s["words"]) == s["tick"] and mcell.words_digest(s["words"]) == s["digest"], f"seed {s['fsid']}: words are the tick and the digest")
        check(s["lead"] == arrival[s["level"]] - s["tick"] > 0 and s["level"] < mcell.TARGETS_TOTAL, f"seed {s['fsid']}: strictly ahead at a live level")
        check(mcell.level_of_mask(int(s["key"][3])) == s["level"] and s["tick"] <= bound and s["slack"] == bound - s["tick"] + 1, f"seed {s['fsid']}: key level and E7")
        check(s["lineage"]["depth"] >= (1 if s["origin"]["kind"] == "burst" else 0) and s["lineage"]["root_origin"]["kind"] == "probe", f"seed {s['fsid']}: lineage {s['lineage']}")
    order = [(-s["level"], -s["lead"], s["tick"], s["fsid"]) for s in seeds]
    check(order == sorted(order), "ordered by (level desc, lead desc)")
    check(len({tuple(s["key"]) for s in seeds}) == len(seeds) == len({s["digest"] for s in seeds}), "one seed per cell key and per prefix")
    # every burst-origin ahead-of-pace arrival of the frontier is at a level <= D, and D is the deepest with at least one
    check(max(int(lv) for lv in sr["burst_ahead_arrivals_per_level"]) == sr["deepest_burst_level"] and all(v > 0 for v in sr["burst_ahead_arrivals_per_level"].values()),
          f"the arrivals per level {sr['burst_ahead_arrivals_per_level']}")
    # the other order: the top S by lead over both levels, still one per key
    S2 = cs.seed_rule(F, arrival, bound, cs.Params(seed_order="lead"))
    leads = [s["lead"] for s in S2["seeds"]]
    check(leads == sorted(leads, reverse=True) and len(S2["seeds"]) == cs.Params.seeds and {s["level"] for s in S2["seeds"]} == {6, 7}, "the lead order pools both levels")
    check(S2["seed_set_digest"] != p["seed_set_digest"], "a different order is a different seed set")
    # deterministic, no words in the rows, the frontier's identity recorded, the arm, the fit
    P2 = cs.build_search_plan(LAB, P["frontier_dir"], cs.Params())
    check(P2["plan"]["seed_set_digest"] == p["seed_set_digest"] and [s["digest"] for s in P2["seeds"]] == [s["digest"] for s in seeds], "the plan is deterministic")
    rows = [cs.seed_row(s) for s in seeds]
    check(all("words" not in r and "words_hex" not in json.dumps(r) for r in rows), "seed rows carry lengths and digests, not words")
    check(p["frontier"]["contract"] == cs.FRONTIER_CONTRACT and p["route"]["digest"] == R["meta"]["native_action_digest"] and p["arrival_by_level"] == {str(k): v for k, v in arrival.items()},
          "the frontier's identity and the reference are recorded")
    check(cs.ARM_BASE == {"segment_words": 120, "max_segments": 4, "window": 20} and cs.Params().arm() == {"segment_words": 120, "max_segments": 6, "window": 20}, f"the arm {cs.Params().arm()}")
    dig_now = fr.code_digest(fr.code_manifest())
    check(dig_now == p["frontier"]["lab_code_digest"], f"the lab code digest {dig_now[:16]} is the frontier's {str(p['frontier']['lab_code_digest'])[:16]}")
    fit = p["throughput_fit"]
    check(fit["jobs"] > 0 and fit["wall_s_fixed"] > 0 and fit["wall_s_per_tick"] > 0 and 0 < fit["efficiency"] <= 1.0, f"the throughput fit {fit}")
    proj = cs.projection(fit, seeds, cs.Params(), bound, 5, 7.0)
    check(proj["available"] and all(r["dispatches_per_h"] > 0 for r in proj["rows"]) and proj["memory"]["bytes_per_cell_estimate"] > 0, f"the projection {proj}")
    return {"deepest_burst_level": sr["deepest_burst_level"], "pool": sr["per_level_pool"], "seeds_per_level": {lv: d["seeds"] for lv, d in p["per_level"].items()},
            "top": [(s["level"], s["tick"], s["lead"]) for s in seeds[:6]], "lineage_depth": p["lineage_depth"], "seed_ticks": p["seed_ticks"], "lab_code_digest": dig_now[:16],
            "projection": {r["prefix"] + "/" + str(r["burst_words"]): r["dispatches_per_h"] for r in proj["rows"]}}


@real
def real_seed_prefixes_rederive_from_frontier_rows() -> Dict[str, Any]:
    """Every seed's prefix re-derived independently here: link by link from the frontier's dispatch rows (the keyed stream of the parent's
    family and iteration) down to its probe start, whose words are the frontier search's own plan on the import (loaded here)."""
    P = real_plan()
    F, seeds, meta = P["F"], P["seeds"], P["meta"]
    rows = {(int(r["round"]), int(r["sid"]), int(r["k"])): r for r in F["rows"] if r.get("kind") == "burst"}
    links = 0
    roots: Dict[int, bytes] = {}
    for s in seeds:
        words, origin, tick, sid = bytes(s["words"]), dict(s["origin"]), s["tick"], s["fsid"]
        while origin["kind"] == "burst":
            parent = F["states"][int(origin["parent"])]
            row = rows[(int(origin["round"]), int(origin["parent"]), int(origin["k"]))]
            burst = bytes.fromhex(row["words_hex"])
            pw = bytes.fromhex(parent["words_hex"])
            off = tick - int(parent["tick"])
            check(1 <= off <= len(burst) and row["draw_id"] == f"{meta['archive_id']}|frontier|{parent['digest']}", f"seed {s['fsid']}: link at {tick}")
            check(fa.stream_words(row["draw_id"], int(origin["k"]), len(burst)) == burst, f"seed {s['fsid']}: the burst re-derives from its key family")
            check(words == pw + burst[:off], f"seed {s['fsid']}: the prefix is the parent's plus the burst to the arrival")
            check(int(row["levels"].get(str(s["level"])) or -1) == s["tick"] if int(parent["sid"]) == int(s["origin"]["parent"]) and parent["level"] < s["level"] else True,
                  f"seed {s['fsid']}: the arrival is in the row's levels reading")
            words, tick, sid, origin = pw, int(parent["tick"]), int(parent["sid"]), dict(parent["origin"])
            links += 1
        check(origin["kind"] == "probe" and F["starts"][sid]["digest"] == mcell.words_digest(words) and s["lineage"]["root_sid"] == sid, f"seed {s['fsid']}: the probe root")
        roots[sid] = words
    # the probe roots against the frontier search's own start rule on the import (its zero-tick plan, built here)
    lab, _meta, R_fs = fs.load_all(LAB)                                  # the frontier planner's own reference record (with the route's trace)
    probe = fs.read_probe(Path(F["plan"]["probe"]["dir"]))
    check(R_fs["meta"]["native_action_digest"] == P["R"]["meta"]["native_action_digest"] and R_fs["arrival"] == P["R"]["arrival"], "the same reference clear")
    S = fs.build_search_plan(lab, R_fs, probe, fs.Params(**{k: v for k, v in F["plan"]["params"].items() if k != "keep_slots"}))
    init = {st.sid: st for st in S["beam"].initial()}
    check(S["plan"]["start_set_digest"] == F["plan"]["start_set_digest"], "the frontier's start set rebuilds from the import")
    for sid, words in roots.items():
        check(init[sid].words == words and init[sid].tick == len(words), f"probe root {sid}: the frontier's initial start on the import")
    return {"seeds": len(seeds), "links": links, "probe_roots": len(roots), "root_sids": sorted(roots)}


# =============================================================================================================================================
# the archive: keep / replace, E7, selection (zero native ticks, synthetic keys)
# =============================================================================================================================================


def mask_of(level: int) -> int:
    return (1 << (mcell.TARGETS_TOTAL - level)) - 1


def key_of(x: int, level: int, y: int = 0, res: str = "A2") -> Tuple[int, int, str, int, int]:
    return (x, y, res, mask_of(level), -1)


def words_for(tick: int, tag: int) -> bytes:
    return bytes((tag * 31 + i) % len(mcell.TRIPLES) for i in range(tick))


def obs_for(t: int) -> Tuple[Any, ...]:
    return (t,) * len(mcell.OBS_FIELDS)


@synthetic
def archive_keep_replace_and_e7() -> Dict[str, Any]:
    arrival = {lv: 100 * lv for lv in range(mcell.TARGETS_TOTAL + 1)}
    bound = 1000 - 24 - 1
    for bad in (dict(seeds=0), dict(seed_order="x"), dict(level_decay=0.0), dict(level_decay=1.5), dict(novelty_exp=-1), dict(max_segments=0), dict(max_cells=0), dict(retire_after=-1)):
        try:
            cs.Params(**bad).check()
            raise AssertionError(f"params {bad} were accepted")
        except cs.SearchError:
            pass
    a = cs.Archive("arch", arrival, bound, cs.Params())
    # a seed at level 7, tick 500
    v, s7 = a.keep(key_of(0, 7), 7, 500, words_for(500, 1), obs_for(500), b"\x01" * 32, b"\x02" * 32, {"kind": "seed"}, 0)
    check(v == cs.NEW and s7 is not None and s7.cid == 0 and s7.lead == 200 and a.slack_of(500) == bound - 499 and a.eligible(s7) and s7.first_level_reach, "the first cell")
    check(s7.draw_id("arch") == f"arch|crossing|{s7.digest}" and s7.digest == mcell.words_digest(words_for(500, 1)), "the draw id is the archive id, the key family, the prefix digest")
    # reaches of a burst from it: new keys, its own key (skipped), a later arrival (a visit), an earlier arrival (replaces), beyond E7, terminal, cleared
    v1, c1 = a.keep(key_of(1, 7), 7, 560, words_for(560, 2), obs_for(560), b"\x03" * 32, b"\x04" * 32, {"kind": "burst", "parent": 0}, 1, self_key=key_of(0, 7))
    v_self, _ = a.keep(key_of(0, 7), 7, 501, words_for(501, 2), obs_for(501), b"\x03" * 32, b"\x04" * 32, {"kind": "burst", "parent": 0}, 1, self_key=key_of(0, 7))
    v_later, c_later = a.keep(key_of(1, 7), 7, 600, words_for(600, 3), obs_for(600), b"\x05" * 32, b"\x06" * 32, {"kind": "burst", "parent": 0}, 2)
    check(v1 == cs.NEW and c1.cid == 1 and v_self == cs.SELF and v_later == cs.LATER and c_later is c1 and c1.seen == 1 and c1.tick == 560 and len(a.cells) == 2, "new, self, later")
    c1.dispatched = c1.fresh = 3
    v_rep, c_rep = a.keep(key_of(1, 7), 7, 540, words_for(540, 4), obs_for(540), b"\x07" * 32, b"\x08" * 32, {"kind": "burst", "parent": 0, "k": 9}, 3)
    check(v_rep == cs.REPLACED and c_rep is c1 and c1.tick == 540 and c1.lead == 160 and c1.words == words_for(540, 4) and c1.end == obs_for(540) and c1.end_digest == b"\x07" * 32
          and c1.fresh == 0 and c1.dispatched == 3 and c1.seen == 2 and c1.replaced == 1 and c1.previous["tick"] == 560 and c1.origin["k"] == 9 and c1.created_at == 3, "a faster arrival replaces the representative")
    v_b, c_b = a.keep(key_of(2, 7), 7, bound + 1, words_for(bound + 1, 5), obs_for(1), b"\x09" * 32, b"\x0a" * 32, {"kind": "burst"}, 4)
    v_e, c_e = a.keep(key_of(3, 7), 7, bound, words_for(bound, 6), obs_for(1), b"\x09" * 32, b"\x0a" * 32, {"kind": "burst"}, 4)
    check(v_b == cs.BEYOND and c_b is None and v_e == cs.NEW and c_e is not None and a.eligible(c_e) and c_e.lead == 700 - bound and a.slack_of(c_e.tick) == 1, "the E7 bound: at the bound kept and eligible, past it never kept")
    v_t, _ = a.keep(key_of(4, 7), 7, 700, words_for(700, 7), obs_for(1), b"\x09" * 32, b"\x0a" * 32, {"kind": "burst"}, 5, terminal=True)
    v_d, _ = a.keep(key_of(5, mcell.TARGETS_TOTAL), mcell.TARGETS_TOTAL, 700, words_for(700, 8), obs_for(1), b"\x09" * 32, b"\x0a" * 32, {"kind": "burst"}, 5)
    check(v_t == cs.TERMINAL and v_d == cs.DEEP and len(a.cells) == 3, "terminal reaches and cleared masks are never cells")
    for bad in ((key_of(6, 8), 7, 700, words_for(700, 9)), (key_of(6, 7), 7, 700, words_for(699, 9))):
        try:
            a.keep(bad[0], bad[1], bad[2], bad[3], obs_for(1), b"\x09" * 32, b"\x0a" * 32, {"kind": "burst"}, 6)
            raise AssertionError(f"keep accepted {bad[:3]}")
        except cs.SearchError:
            pass
    # deeper levels: the earliest arrival per level, the deepest reading
    v8, c8 = a.keep(key_of(0, 8), 8, 650, words_for(650, 10), obs_for(650), b"\x0b" * 32, b"\x0c" * 32, {"kind": "burst", "parent": 1}, 7)
    v8b, c8b = a.keep(key_of(1, 8), 8, 640, words_for(640, 11), obs_for(640), b"\x0d" * 32, b"\x0e" * 32, {"kind": "burst", "parent": 1}, 8)
    check(v8 == cs.NEW and c8.first_level_reach and v8b == cs.NEW and not c8b.first_level_reach and a.earliest[8]["tick"] == 640 and a.earliest[8]["cid"] == c8b.cid
          and a.deepest()["level"] == 8 and a.deepest()["tick"] == 640 and a.deepest()["reference"] == 800, f"the earliest per level {a.earliest}")
    check(a.levels_present() == [7, 8] and sorted(a.eligible_cids(7)) == [0, 1, 2] and a.eligible_cids(8) == [3, 4], "levels and eligible cells")
    # quarantine and retirement make a cell ineligible but keep its key; a replacement lifts both
    a.quarantine(c_e, "prefix mismatch")
    check(not a.eligible(c_e) and c_e.words is None and a.by_key[key_of(3, 7)] == c_e.cid and sorted(a.eligible_cids(7)) == [0, 1], "quarantine")
    v_q, _ = a.keep(key_of(3, 7), 7, bound, words_for(bound, 12), obs_for(1), b"\x09" * 32, b"\x0a" * 32, {"kind": "burst"}, 9)
    check(v_q == cs.LATER and not a.eligible(c_e), "an equal arrival at a quarantined key is a visit")
    v_q2, _ = a.keep(key_of(3, 7), 7, bound - 10, words_for(bound - 10, 13), obs_for(1), b"\x09" * 32, b"\x0a" * 32, {"kind": "burst"}, 9)
    check(v_q2 == cs.REPLACED and a.eligible(c_e) and c_e.quarantined is None, "a faster arrival at a quarantined key is a fresh start")
    a2 = cs.Archive("arch", arrival, bound, cs.Params(retire_after=5))
    _v, r = a2.keep(key_of(0, 7), 7, 500, words_for(500, 1), obs_for(500), b"\x01" * 32, b"\x02" * 32, {"kind": "seed"}, 0)
    r.dispatched = r.fresh = 4
    check(not a2.retire_check(r, "t") and r.alive(), "not yet")
    r.dispatched = r.fresh = 5
    r.breaks = 1
    check(not a2.retire_check(r, "t"), "a break record prevents retirement")
    r.breaks = 0
    r.new_children = 1
    check(not a2.retire_check(r, "t"), "a new cell prevents retirement")
    r.new_children = 0
    check(a2.retire_check(r, "t") and not r.alive() and r.words is None and a2.counts["retired"] == 1 and not a.p.retire_after, "retirement after R dispatches without any event; off by default")
    # the continuation trigger on this archive: a new key or an earlier arrival continues, a known key at a later tick does not
    d1 = a.continuation_decision([[700, list(key_of(40, 7))]])
    d2 = a.continuation_decision([[560, list(key_of(1, 7))]])
    d3 = a.continuation_decision([[530, list(key_of(1, 7))]])
    check(d1["go"] and d1["new"] == 1 and not d2["go"] and d2["shorter"] == 0 and d3["go"] and d3["shorter"] == 1 and d3["max_gain"] == 10, f"the F3 trigger {d1} {d2} {d3}")
    st = a.stats()
    check(st["cells"] == 5 and st["new"] == 5 and st["replaced"] == 2 and st["later"] == 2 and st["self"] == 1 and st["beyond"] == 1 and st["terminal"] == 1 and st["deep"] == 1
          and st["deepest_level"] == 8 and st["words_mb"] >= 0, f"stats {st}")
    pl = a.per_level()
    check(list(pl) == ["8", "7"] and pl["7"]["cells"] == 3 and pl["7"]["earliest_tick"] == 500 and pl["7"]["best_lead"] == 200 and pl["8"]["earliest_tick"] == 640, f"per level {pl}")
    return {"counts": a.counts, "earliest": {str(k): v["tick"] for k, v in a.earliest.items()}}


@synthetic
def selection_on_stub_archives() -> Dict[str, Any]:
    arrival = {lv: 200 * lv for lv in range(mcell.TARGETS_TOTAL + 1)}
    bound = 2000 - 24 - 1

    def build(params: cs.Params, levels: Sequence[Tuple[int, int, int]]) -> cs.Archive:
        a = cs.Archive("arch", arrival, bound, params)
        for i, (lv, tick, tag) in enumerate(levels):
            v, _c = a.keep(key_of(tag, lv), lv, tick, words_for(tick, tag), obs_for(tick), bytes([tag % 256]) * 32, bytes([(tag + 1) % 256]) * 32, {"kind": "seed"}, i)
            check(v == cs.NEW, "distinct keys")
        return a

    def draws(a: cs.Archive, n: int, seed: int = 7) -> Dict[int, int]:
        a.refresh()                                                      # the tests edit cell statistics directly: recompute every cached weight
        rng = random.Random(seed)
        out: Dict[int, int] = {}
        for _ in range(n):
            pick = a.select(rng)
            check(pick is not None, "a draw")
            c, d = pick
            check(a.eligible(c) and 0 < d["p_level"] <= 1 and d["w_share"] is not None and d["level_eligible"] >= 1 and abs(sum(d["levels"].values()) - 1.0) < 1e-3, f"the draw record {d}")
            out[c.cid] = out.get(c.cid, 0) + 1
        return out

    # the level draw: decay 1/2 over levels 6, 7, 8 (one cell each, equal within-level weights) -> shares 1/7, 2/7, 4/7
    a = build(cs.Params(pace_exp=0.0), [(6, 600, 1), (7, 600, 2), (8, 600, 3)])
    lw = a.level_weights()
    check(lw == {6: 0.25, 7: 0.5, 8: 1.0}, f"level weights {lw}")
    n = draws(a, 7000)
    check(abs(n[2] / 7000 - 4 / 7) < 0.03 and abs(n[1] / 7000 - 2 / 7) < 0.03 and abs(n[0] / 7000 - 1 / 7) < 0.03, f"level shares {n}")
    # decay 1 = uniform over levels; decay 0.1 = almost only the deepest
    check(build(cs.Params(level_decay=1.0), [(6, 600, 1), (8, 600, 3)]).level_weights() == {6: 1.0, 8: 1.0}, "decay 1 is flat")
    n01 = draws(build(cs.Params(level_decay=0.1, pace_exp=0.0), [(6, 600, 1), (8, 600, 3)]), 2000)
    check(n01.get(1, 0) > 1700, f"decay 0.1 concentrates on the deepest level {n01}")
    # novelty within a level: a cell dispatched 9 times is drawn about a tenth as often as a fresh one
    a = build(cs.Params(pace_exp=0.0), [(7, 600, 1), (7, 600, 2)])
    a.cells[1].fresh = a.cells[1].dispatched = 9
    n = draws(a, 6000)
    check(0.07 < n.get(1, 0) / n[0] < 0.14, f"novelty {n}")
    # the seen penalty: seen 9 is drawn a tenth as often; switched off, equally
    a = build(cs.Params(pace_exp=0.0), [(7, 600, 1), (7, 600, 2)])
    a.cells[1].seen = 9
    n = draws(a, 6000)
    check(0.07 < n.get(1, 0) / n[0] < 0.14, f"seen penalty {n}")
    a.p = cs.Params(pace_exp=0.0, seen_exp=0.0)
    n = draws(a, 6000)
    check(0.85 < n.get(1, 0) / n[0] < 1.18, f"seen penalty off {n}")
    # the break bonus: a cell with 3 breaks is drawn four times as often; off, equally
    a = build(cs.Params(pace_exp=0.0), [(7, 600, 1), (7, 600, 2)])
    a.cells[1].breaks = 3
    n = draws(a, 6000)
    check(3.3 < n[1] / n[0] < 4.8, f"bonus {n}")
    a.p = cs.Params(pace_exp=0.0, bonus_exp=0.0)
    n = draws(a, 6000)
    check(0.85 < n[1] / n[0] < 1.18, f"bonus off {n}")
    # the pace term: slack^0.5; a cell at tick 1951 (slack 25) against one at tick 1376 (slack 600): ratio sqrt(24)
    a = build(cs.Params(), [(7, 1951, 1), (7, 1376, 2)])
    n = draws(a, 8000)
    check(3.8 < n[1] / n[0] < 6.2, f"pace {n}")
    # all switches off and decay 1: every eligible cell equally likely across levels with one cell each
    a = build(cs.Params(level_decay=1.0, novelty_exp=0.0, seen_exp=0.0, bonus_exp=0.0, pace_exp=0.0), [(6, 600, 1), (7, 900, 2), (8, 1200, 3)])
    a.cells[0].fresh, a.cells[1].seen, a.cells[2].breaks = 20, 20, 5
    n = draws(a, 6000)
    check(all(0.28 < v / 6000 < 0.39 for v in n.values()), f"flat {n}")
    # an ineligible cell is never drawn; an empty archive draws nothing; the deepest level is read on eligible cells only
    a = build(cs.Params(), [(7, 600, 1), (8, 700, 2)])
    a.quarantine(a.cells[1], "x")
    n = draws(a, 200)
    check(set(n) == {0} and a.level_weights() == {7: 1.0}, "a quarantined cell is never drawn and does not set the deepest level")
    a.quarantine(a.cells[0], "x")
    check(a.select(random.Random(1)) is None and a.level_weights() == {}, "an empty archive")
    # the cached weights follow the cells' statistics through touch (the engine's path) and refresh (the tests' path)
    a = build(cs.Params(pace_exp=0.0), [(7, 600, 1), (7, 600, 2)])
    draws(a, 10)
    a.cells[1].fresh = 99
    a.touch(a.cells[1])
    n = {}
    rng = random.Random(3)
    for _ in range(500):
        c, _d = a.select(rng)
        n[c.cid] = n.get(c.cid, 0) + 1
    check(n.get(1, 0) < 25 and n[0] > 450, f"a touched cell's new weight is used at the next draw {n}")
    # reproducible draws from the Python seed
    a = build(cs.Params(), [(6, 600, 1), (7, 700, 2), (7, 800, 3), (8, 900, 4)])
    r1, r2 = random.Random(5), random.Random(5)
    check([a.select(r1)[0].cid for _ in range(50)] == [a.select(r2)[0].cid for _ in range(50)], "the draws are reproducible from the experiment seed")
    return {"level_shares": {str(k): round(v / 7000, 3) for k, v in sorted(draws(build(cs.Params(pace_exp=0.0), [(6, 600, 1), (7, 600, 2), (8, 600, 3)]), 7000).items())}}


# =============================================================================================================================================
# the guard refusals
# =============================================================================================================================================


def fake_frontier(lab: Path, name: str) -> Path:
    fd = lab / name
    (fd / "run" / "frontier").mkdir(parents=True)
    for f in cs.FRONTIER_FILES:
        (fd / f).parent.mkdir(parents=True, exist_ok=True)
        (fd / f).write_text("", encoding="utf-8")
    return fd


@synthetic
def guard_refusals() -> Dict[str, Any]:
    lab = tmpdir("lab")
    (lab / "import").mkdir()
    (lab / "import" / "import_manifest.json").write_text("{}", encoding="utf-8")
    frontier = fake_frontier(lab, "fakefrontier_x")                      # never matches the frontier_* default lookup; its files are empty, so reading it is refused
    bad_out = [REPO / "crossing_x", REPO / "runs" / "crossing_x", REPO / "logs" / "crossing_x", lab / "runs" / "x", lab.parent / "elsewhere_x",
               Path("D:/BattleShip_runs_backup/x"), Path("D:/BattleShip_source_snapshots/x"), Path("D:/BattleShip_exe_archive/x")]
    for b in bad_out:
        try:
            g.validate_run_dir(b, lab)
            raise AssertionError(f"output folder {b} was accepted")
        except g.LabRootError:
            pass
    check(g.validate_run_dir(lab / "crossing_2026-01-01", lab) == lab / "crossing_2026-01-01", "an output folder inside the lab root is accepted")
    try:
        g.LabFS(lab).write_text(REPO / "logs" / f"crossing_guard_{os.getpid()}.tmp", "must never exist")
        raise AssertionError("LabFS wrote outside the lab root")
    except g.LabRootError:
        pass
    for bad in (lab / "import", frontier):
        try:
            cs.read_frontier(bad)
            raise AssertionError(f"{bad} was accepted as a frontier folder")
        except (cs.SearchError, ValueError):
            pass
    exits = {}
    base = ["plan", "--lab-root", str(lab), "--frontier", str(frontier)]
    for argv in (base + ["--out", str(REPO / "crossing_x")], base + ["--out", str(lab / "runs" / "x")], ["plan", "--lab-root", str(REPO / "lab_x")],
                 base + ["--workers", "6"], base + ["--seeds", "0"], base + ["--level-decay", "0"], base + ["--max-segments", "0"], base + ["--max-wall-min", "0"],
                 base + ["--seed-order", "x"], ["plan", "--lab-root", str(lab), "--frontier", str(REPO / "runs" / "x")],
                 ["plan", "--lab-root", str(lab), "--frontier", str(lab.parent / "elsewhere")], ["plan", "--lab-root", str(lab), "--frontier", str(lab / "import")],
                 ["plan", "--lab-root", str(lab)]):
        try:
            cs.main(argv)
            raise AssertionError(f"main accepted {argv}")
        except SystemExit as exc:
            exits[" ".join(argv[1:])[-70:]] = str(exc)[:80]
        check(not g.LabGuard.installed, f"the refusal of {argv[1:]} happened before the guard was armed in this process")
    st = g.guard_selftest(lab)                                        # a child process arms the guard on the real checkout and evidence roots
    check(st["ok"], f"the guard self-test on the temporary lab root: {json.dumps(st, default=str)[:600]}")
    return {"refused_outputs": len(bad_out), "main_refusals": len(exits), "guard_child": st["child"]}


# =============================================================================================================================================
# the verification verdicts (stub traces)
# =============================================================================================================================================


@synthetic
def verification_verdicts() -> Dict[str, Any]:
    words, claim = T.stub_clear("easy")
    cand = {"n": 12, "cid": 5, "k": 1, "level": 8, "start_tick": 10, "lead": 3, "words": words, "claim": claim}
    t = claim["completion_input_tick"]
    rows = {}
    rows["ok"] = cs.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, claim, "c1", 0), t + 1)
    rows["same"] = cs.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, claim, "c2", 0), t)
    rows["slower"] = cs.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, claim, "c3", 0), t - 5)
    rows["tamper"] = cs.clear_row(cand, fv.verify_twice(T.stub_replay(tamper_second=True), stub.analyse, words, claim, "c4", 0), t + 1)
    rows["error"] = cs.clear_row(cand, fv.verify_twice(T.stub_replay(fail=10), stub.analyse, words, claim, "c5", 0), t + 1)
    rows["clock"] = cs.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, dict(claim, completion_input_tick=t - 1), "c6", 0), t + 1)
    rows["chain"] = cs.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, dict(claim, chain="0" * 64), "c7", 0), t + 1)
    r = rows["ok"]
    check(r["verdict"] == fv.VERIFIED and r["faster_than_reference"] and r["gain_vs_reference"] == 1 and r["chain_r1"] == r["chain_r2"] == claim["chain"]
          and r["clocks_r1"] == r["clocks_r2"] == [t, t - 1] and r["breaks_r1"] == r["breaks_r2"] and r["words_digest"] == claim["words_digest"]
          and r["words_hex"] == words.hex() and r["n"] == 12 and r["cid"] == 5, f"VERIFIED row {r['reasons']}")
    check(rows["same"]["verdict"] == fv.VERIFIED and not rows["same"]["faster_than_reference"] and rows["same"]["gain_vs_reference"] == 0, "a clear at the reference's tick is not faster")
    check(rows["slower"]["verdict"] == fv.VERIFIED and not rows["slower"]["faster_than_reference"] and rows["slower"]["gain_vs_reference"] == -5, "a slower verified clear")
    check(rows["tamper"]["verdict"] == fv.NONDETERMINISTIC and not rows["tamper"]["faster_than_reference"] and rows["tamper"]["gain_vs_reference"] is None
          and rows["tamper"]["chain_r1"] != rows["tamper"]["chain_r2"], "two replays that disagree are NONDETERMINISTIC and never a clear")
    check(rows["error"]["verdict"] == fv.ERROR and not rows["error"]["faster_than_reference"] and rows["error"]["chain_r1"] is None, "a replay that cannot run is ERROR")
    check(rows["clock"]["verdict"] == fv.NONDETERMINISTIC and rows["chain"]["verdict"] == fv.NONDETERMINISTIC, "a claim the replay does not reproduce is never a clear")
    # the seed check on stub traces: the recorded chain, record digest and key must be reproduced
    clf = mcell.Classifier()
    prefix = words[:40]
    tr = stub.replay_trace("easy", prefix, "s")
    last = tr["steps"][-1]
    key = mcell.cell_key(last["observation"], last["spatial"], clf)
    rec = {"fsid": 1, "level": mcell.level_of_mask(key[3]), "chain": fv.chain_of(tr["initial"], tr["steps"]).hex(), "end_digest": mcell.record_digest(mcell.record_of(last)).hex(),
           "key": list(key)}
    ok = cs.seed_check(stub.replay_trace("easy", prefix, "s2"), prefix, rec, stub.analyse, clf)
    check(ok["ok"] and ok["end"] == mcell.obs_tuple(last["observation"]) and ok["ticks"] == 40 and ok["ticks_ok"] and ok["key"] == list(key), f"a seed that reproduces {ok}")
    bad_chain = cs.seed_check(stub.replay_trace("easy", prefix, "s3"), prefix, dict(rec, chain="0" * 64), stub.analyse, clf)
    bad_key = cs.seed_check(stub.replay_trace("easy", prefix, "s4"), prefix, dict(rec, key=[99, 99, "A2", key[3], -1]), stub.analyse, clf)
    bad_level = cs.seed_check(stub.replay_trace("easy", prefix, "s5"), prefix, dict(rec, level=rec["level"] + 1), stub.analyse, clf)
    none = cs.seed_check(None, prefix, rec, stub.analyse, clf)
    check(not bad_chain["ok"] and "chain_equal" in bad_chain["why"] and not bad_key["ok"] and "key_equal" in bad_key["why"] and not bad_level["ok"] and not none["ok"],
          f"a seed that does not reproduce is dropped: {bad_chain['why']} / {bad_key['why']} / {bad_level['why']} / {none['why']}")
    full = cs.seed_check(stub.replay_trace("easy", words, "s6"), words, dict(rec, level=0), stub.analyse, clf)
    check(not full["ok"] and "not live" in full["why"], "a prefix that ends the episode is not a seed")
    return {"clear_ticks": t, "verdicts": {k: v["verdict"] for k, v in rows.items()}}


# =============================================================================================================================================
# the synthetic end-to-end run (stub world: a synthetic probe, the frontier search's engine on it, then the crossing search on that output)
# =============================================================================================================================================


RUN_CHILD = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, {rl!r}); sys.path.insert(0, {here!r})
import frs_guard as g
lab = Path({lab!r})
g.LabGuard.install(lab)
import frs_machine as fm, frs_run as fr, m8_rd_stub as stub, crossing_search as cs
out = Path({out!r}); run_dir = out / {run_name!r}; frontier = Path({frontier!r})
params = cs.Params(**{params!r})
P = cs.plan_and_write(lab, frontier, out, params, stub.analyse)
env = fr.LabEnv(worker_spec=lambda rank: {{"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": "easy", "inject": {{}},
                                           "failure_dir": str(run_dir / "failures"), "guard": g.LabGuard.spec()}},
                replay=lambda words, label, slot: stub.replay_trace("easy", words, label), analyse=stub.analyse,
                readiness=lambda: {{"ok": True, "problems": []}}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot, import_problems=lambda: [],
                wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend="stub", sample_s=0.25, row_every_s=0.5,
                caps=dict(fm.CAPS_MB, main_private=1e9))
cfg = cs.SearchConfig(lab_root=lab, out=out, run_dir=run_dir, frontier_dir=frontier, n_workers=2, max_ticks={max_ticks!r}, max_wall_s={max_wall!r},
                      expect_code={expect!r}, stop_grace_s=10.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0, seed_parallel=2)
code = cs.Search(cfg, env, P, params).run()
print(json.dumps({{"code": code, "violations": g.LabGuard.violations[:3], "seeds": P["plan"]["seeds"], "bound": P["bound"]}}))
'''


def child_code(lab: Path, out: Path, frontier: Path, run_name: str, params: Dict[str, Any], *, max_ticks: int = 10 ** 9, max_wall: float = 300.0,
               expect: Optional[str] = None) -> str:
    return RUN_CHILD.format(rl=str(RL), here=str(HERE), lab=str(lab), out=str(out), run_name=run_name, frontier=str(frontier), params=params, max_ticks=max_ticks,
                            max_wall=max_wall, expect=expect)


def synthetic_frontier(lab: Path) -> Dict[str, Any]:
    """A frontier search output folder made IN the stub world: the synthetic probe (frontier_search_tests.synthetic_probe), then the frontier
    search's own engine in a guarded child for a few rounds in mode `reaches`. THE WORLD IS SYNTHETIC."""
    info = fst.synthetic_probe(lab, per_start=2)
    check(info["ahead"] > 0, f"the synthetic probe recorded no level arrival ahead of its route: {info}")
    out = lab / "frontier_syn"
    params = {"bursts": 2, "frontier": 8, "share": 0.25, "bonus": 1, "retire_after": 6, "candidates": "reaches", "reserve": 60, "max_rounds": 5}
    expect = fr.code_digest(fr.code_manifest())
    res = fst.run_child(fst.child_code(lab, out, info["out"], "run", params, expect=expect))
    check(res["code"] == 0 and not res["violations"], f"the synthetic frontier run: {res}")
    F = cs.read_frontier(out)
    D, per = cs.deepest_burst_level(F["rows"])
    check(D is not None and D >= 1 and len(F["states"]) > 0, f"the synthetic frontier reached no level ahead of pace: {per}")
    return {"probe": info, "out": out, "deepest_burst_level": D, "arrivals": per, "states": len(F["states"]), "expect": expect}


@synthetic
def stub_end_to_end() -> Dict[str, Any]:
    lab = tmpdir("lab")
    syn = synthetic_frontier(lab)
    frontier, out, expect = syn["out"], lab / "crossing_test", syn["expect"]
    params = {"seeds": 12, "seed_order": "level", "level_decay": 0.5, "novelty_exp": 1.0, "seen_exp": 1.0, "bonus_exp": 1.0, "pace_exp": 0.5, "max_segments": 3,
              "retire_after": 0, "max_cells": 100000, "max_dispatches": 320, "rng_seed": 3}
    # the plan refuses to overwrite a different seed set, accepts the same one again; its seed rows carry no words
    out.mkdir()
    (out / "plan.json").write_text(json.dumps({"seed_set_digest": "0" * 64}), encoding="utf-8")
    try:
        cs.plan_and_write(lab, frontier, out, cs.Params(**params), stub.analyse)
        raise AssertionError("a different saved seed set was overwritten")
    except cs.SearchError:
        pass
    (out / "plan.json").unlink()
    P = cs.plan_and_write(lab, frontier, out, cs.Params(**params), stub.analyse)
    P2 = cs.plan_and_write(lab, frontier, out, cs.Params(**params), stub.analyse)
    p = P["plan"]
    check(p["seeds"] > 0 and p["seed_set_digest"] == P2["plan"]["seed_set_digest"] and len(read_jsonl(out / "seeds.jsonl")) == p["seeds"], "the plan is deterministic")
    check("words_hex" not in (out / "seeds.jsonl").read_text(encoding="utf-8"), "seeds.jsonl carries no words")
    check(p["seed_rule"]["deepest_burst_level"] == syn["deepest_burst_level"] and all(s["lineage"]["root_origin"]["kind"] == "probe" for s in P["seeds"]), "the seed rule on the synthetic frontier")
    seed_levels = {s["level"] for s in P["seeds"]}
    check(seed_levels <= {syn["deepest_burst_level"], syn["deepest_burst_level"] - 1}, f"seed levels {seed_levels}")
    # the wrong lab code digest is refused at open (nothing launched)
    res0 = fst.run_child(child_code(lab, out, frontier, "run_badcode", params, expect="0" * 64))
    check(res0["code"] == 2 and any(f.name.startswith("refused_") for f in out.iterdir()) and not (out / "run_badcode").exists(), f"a wrong lab code digest is refused: {res0}")
    # the run
    res = fst.run_child(child_code(lab, out, frontier, "run", params, expect=expect))
    check(res["code"] == 0 and not res["violations"], f"the synthetic run: {res}")
    run_dir = out / "run"
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    rows = read_jsonl(run_dir / "dispatches.jsonl")
    seeds = read_jsonl(run_dir / "seeds.jsonl")
    cells = read_jsonl(run_dir / "cells.jsonl")
    arrival = {int(k): int(v) for k, v in p["arrival_by_level"].items()}
    bound = P["bound"]
    check(s["status"] == "DISPATCH_CAP" and s["work"]["dispatches"] == params["max_dispatches"] and s["work"]["jobs"] >= params["max_dispatches"] - 2, f"{s['status']} {s['stop']} {s['work']}")
    check(s["reference"]["ok"] is True and s["integrity"]["guard_violations_main"] == [] and s["integrity"]["battleship_left"] == []
          and s["integrity"]["lab_code_changed_during_run"] == [] and s["integrity"]["lab_code_digest_end"] == expect, f"{s['reference']} {s['integrity']}")
    # the seeds: every one replayed from tick 0 and checked against the frontier's record (chain, record digest, key, level), the end record taken from the replay
    check(len(seeds) == p["seeds"] == s["seed"]["seeds"] and all(r["ok"] and r["chain_equal"] and r["end_digest_equal"] and r["key_equal"] and r["level_equal"] and r["ticks_ok"] for r in seeds),
          f"every seed reproduced: {s['seed']}")
    check(s["seed"]["ok"] == len(seeds) and s["seed"]["dropped"] == 0 and sorted(r["cid"] for r in seeds) == list(range(len(seeds))), f"the seed stats {s['seed']}")
    seed_cells = [c for c in cells if c["origin"]["kind"] == "seed"]
    check(len(seed_cells) == len(seeds) and all(c["ev"] == "new" and len(c["words_hex"]) == 2 * c["tick"] for c in seed_cells), "every seed is a cell with its exact prefix")
    # every dispatch: from an archive cell, the prefix reproduced its level and the tick-0 pin, the burst from the cell's key family and iteration
    by_cid: Dict[int, Dict[str, Any]] = {}
    for c in cells:
        by_cid[c["cid"]] = c                                           # the last representative wins
    check(all(r["prefix_level_ok"] and r["tick0_equal"] is True and r["outcome"] not in cs.BAD_OUTCOMES for r in rows), "every prefix reproduced its level and the tick-0 pin")
    check(all(r["cid"] in by_cid and r["draw_id"].startswith(f"{p['archive_id']}|crossing|") for r in rows), "every dispatch is from an archive cell")
    for r in rows:
        burst = bytes.fromhex(r["words_hex"])
        check(fa.stream_words(r["draw_id"], r["k"], len(burst)) == burst, f"dispatch {r['n']}: the burst re-derives from its key family")
    ks: Dict[str, List[int]] = {}
    for r in rows:
        ks.setdefault(r["draw_id"], []).append(r["k"])
    check(all(sorted(v) == list(range(len(v))) for v in ks.values()), "a representative's iterations are 0..n-1, never repeated")
    # the archive: every new cell's prefix is its parent's representative at dispatch plus the burst to the reach; faster arrivals replaced; E7 kept nothing beyond the bound
    rows_by_n = {r["n"]: r for r in rows}                                 # the dispatch number is the unique handle (a replaced representative restarts its iterations)
    check(len(rows_by_n) == len(rows), "dispatch numbers are unique")
    checked = replaced = 0
    for c in cells:
        if c["origin"]["kind"] != "burst":
            continue
        o = c["origin"]
        r = rows_by_n.get(o["n"])
        check(r is not None and r["cid"] == o["parent"] and r["k"] == o["k"], f"cell {c['cid']}: its parent's dispatch row")
        parent_words = None
        for cc in cells:
            if cc["cid"] == o["parent"] and cc["digest"] == o["parent_digest"]:
                parent_words = cc["words_hex"]
                break
        check(parent_words is not None, f"cell {c['cid']}: the parent's representative at dispatch is recorded")
        check(c["words_hex"] == parent_words + r["words_hex"][:2 * o["offset"]] and len(c["words_hex"]) == 2 * c["tick"] and c["tick"] == r["start_tick"] + o["offset"],
              f"cell {c['cid']}: the prefix is the parent's plus the burst to the reach")
        check(c["tick"] <= bound and c["level"] == mcell.level_of_mask(int(c["key"][3])) and c["lead"] == arrival[c["level"]] - c["tick"], f"cell {c['cid']}: E7, level, lead")
        checked += 1
        if c["ev"] == "replaced":
            replaced += 1
            check(c["previous"]["tick"] > c["tick"], f"cell {c['cid']}: a replacement is an earlier arrival")
    check(checked > 0 and s["archive"]["cells"] == len({c["cid"] for c in cells}) and s["archive"]["new"] == sum(1 for c in cells if c["ev"] == "new")
          and s["archive"]["replaced"] == replaced and s["archive"]["beyond"] >= 0, f"the archive {s['archive']}")
    keys = {}
    for c in cells:
        keys.setdefault(tuple(c["key"]), set()).add(c["cid"])
    check(all(len(v) == 1 for v in keys.values()), "one cell per key")
    # a multi-burst chain reached a deeper level than its seed: a cell (or a verified clear's start cell) whose lineage has at least two burst
    # links below its seed and whose level (the clear: level 10) is deeper than the seed's. In the synthetic world the reference arrives at the
    # last live levels within a few ticks of each other, so the seeds sit one level under the clear and the deeper level is the clear itself.
    by_rep = {(c["cid"], c["digest"]): c for c in cells}

    def lineage(row: Dict[str, Any]) -> Tuple[int, int]:
        depth, cur = 0, row
        while cur["origin"]["kind"] == "burst":
            depth += 1
            cur = by_rep[(cur["origin"]["parent"], cur["origin"]["parent_digest"])]
        return depth, cur["level"]

    chains = []
    depths = []
    for c in cells:
        if c["origin"]["kind"] == "burst":
            depth, root_level = lineage(c)
            depths.append(depth)
            if depth >= 2 and c["level"] > root_level:
                chains.append((c["cid"], c["level"], root_level, depth))
    check(depths and max(depths) >= 2, f"chains of kept intermediate cells build up (max depth {max(depths, default=0)})")
    deepest = s["deepest"]
    check(deepest and deepest["level"] >= max(seed_levels) and s["earliest_by_level"][str(deepest["level"])]["tick"] == deepest["tick"], f"the deepest reading {deepest}")
    # clears: every candidate verified twice in fresh processes, identical replays, compared with the reference; progress.md names them at the top
    vrows = read_jsonl(run_dir / "verifications.jsonl") if (run_dir / "verifications.jsonl").is_file() else []
    claimed = [r for r in rows if r["outcome"] == "clear"]
    check(len(vrows) == len(claimed) == s["clears"]["candidates"] >= 1, f"a verified clear is needed: {len(vrows)} of {len(claimed)} claimed")
    check(all(v["verdict"] == fv.VERIFIED and v["chain_r1"] == v["chain_r2"] and v["clocks_r1"] == v["clocks_r2"] and v["reference_completion_input_tick"] == arrival[mcell.TARGETS_TOTAL]
              for v in vrows), "stub clears replay identically")
    check(s["clears"]["verified"] == len(vrows) and s["unverified"] == [] and s["clears"]["best_verified"]["completion_input_tick"] == min(v["completion_input_tick"] for v in vrows), f"{s['clears']}")
    clear_chains = []
    for v in vrows:
        r = rows_by_n[v["n"]]
        check(r["cid"] == v["cid"] and r["k"] == v["k"] and r["outcome"] == "clear", f"verification {v['n']}: its dispatch row")
        start = next(cc for cc in cells if cc["cid"] == v["cid"] and len(cc["words_hex"]) == 2 * r["start_tick"] and v["words_hex"].startswith(cc["words_hex"]))
        check(v["completion_input_tick"] == r["claimed"]["completion_input_tick"] == r["ticks"] and v["words"] == r["ticks"] and v["words_hex"] == start["words_hex"] + r["words_hex"],
              "the verified clock is the in-run claim and the words are the cell's plus the burst")
        check(v["faster_than_reference"] == (v["completion_input_tick"] < arrival[mcell.TARGETS_TOTAL]) and v["gain_vs_reference"] == arrival[mcell.TARGETS_TOTAL] - v["completion_input_tick"], "the comparison")
        depth, root_level = lineage(start)
        if depth >= 2 and mcell.TARGETS_TOTAL > root_level:
            clear_chains.append((v["n"], depth, root_level))
    check(chains or clear_chains, f"a multi-burst chain reached a deeper level than its seed (cells {len(chains)}, clears through chains {len(clear_chains)})")
    prog = (run_dir / "progress.md").read_text(encoding="utf-8")
    head = prog.split("## Cells per level")[0]
    check(prog.startswith("# Crossing search: progress (") and "Final." in prog and "## Verified clears" in head and "## Deepest level and earliest ticks" in head
          and f"| {vrows[0]['n']}, {vrows[0]['cid']}, {vrows[0]['k']} |" in head and f"Deepest level reached: **{deepest['level']}** at tick {deepest['tick']:,}" in head
          and "## Cells per level" in prog, "progress.md: the clears, the deepest level and the cells per level at the top")
    check((run_dir / "report.md").read_text(encoding="utf-8").startswith("# Crossing search run (") and (run_dir / "config.json").is_file() and (run_dir / "memory.jsonl").is_file()
          and (run_dir / "reference.json").is_file() and (run_dir / "state.json").is_file(), "the run folder")
    check(s["memory"]["projection"].get("rows", 0) >= 0 and s["throughput"]["jobs_per_h"] > 0 and s["throughput"]["continuation_rate"] is not None, "the memory projection and the throughput")
    eff = s["effects"]
    check(sum(d["jobs"] for d in eff["bonus"].values()) == s["work"]["jobs"] and sum(d["jobs"] for d in eff["seen"].values()) == s["work"]["jobs"], f"the effect tables cover every job {eff}")
    # a tick cap stops the dispatches cleanly (exit 0, status TICK_CAP, the pending clears verified at the close, summary written)
    cap = p["seed_ticks"] + arrival[mcell.TARGETS_TOTAL] + 4 * (bound + 120 * params["max_segments"]) + 10
    res2 = fst.run_child(child_code(lab, out, frontier, "run_cap", params, max_ticks=cap, expect=expect))
    s2 = json.loads((out / "run_cap" / "summary.json").read_text(encoding="utf-8"))
    check(res2["code"] == 0 and s2["status"] == "TICK_CAP" and s2["work"]["ticks_total"] <= cap and s2["seed"]["ok"] == p["seeds"] and s2["work"]["jobs"] >= 1
          and s2["unverified"] == [] and s2["integrity"]["battleship_left"] == [], f"the tick cap: {s2['status']} {s2['work']} {s2['unverified']}")
    check(s2["clears"]["candidates"] == len(read_jsonl(out / "run_cap" / "verifications.jsonl")) if (out / "run_cap" / "verifications.jsonl").is_file() else s2["clears"]["candidates"] == 0,
          "every pending clear of a capped run is verified at the close")
    check("Final." in (out / "run_cap" / "progress.md").read_text(encoding="utf-8"), "the capped run's final progress")
    # a wall cap stops cleanly too (the deadline falls during the seeds or the first dispatches)
    res3 = fst.run_child(child_code(lab, out, frontier, "run_wall", params, max_wall=20.0, expect=expect))
    s3 = json.loads((out / "run_wall" / "summary.json").read_text(encoding="utf-8"))
    check(res3["code"] == 0 and s3["status"] == "WALL_CAP" and s3["elapsed_s"] < 20.0 + 60.0 and s3["integrity"]["battleship_left"] == [], f"the wall cap: {s3['status']} {s3['elapsed_s']}")
    # a cells cap stops cleanly
    res4 = fst.run_child(child_code(lab, out, frontier, "run_cells", dict(params, max_cells=p["seeds"] + 5, max_dispatches=0), expect=expect))
    s4 = json.loads((out / "run_cells" / "summary.json").read_text(encoding="utf-8"))
    check(res4["code"] == 0 and s4["status"] == "CELLS_CAP" and s4["archive"]["cells"] >= p["seeds"] + 5, f"the cells cap: {s4['status']} {s4['archive']}")
    # a second run into the same run folder is refused (never overwritten): the engine refuses at open, nothing is launched
    res5 = fst.run_child(child_code(lab, out, frontier, "run", params, expect=expect))
    check(res5["code"] == 2, f"an existing run folder is refused: {res5}")
    return {"synthetic": {k: syn[k] for k in ("deepest_burst_level", "arrivals", "states")}, "seeds": p["seeds"], "seed_levels": sorted(seed_levels), "dispatches": s["work"]["dispatches"],
            "cells": s["archive"]["cells"], "replaced": replaced, "max_lineage_depth": max(depths), "deeper_cells_through_chains": len(chains), "clears_through_chains": len(clear_chains),
            "deepest": {k: deepest[k] for k in ("level", "tick")}, "clears_verified": s["clears"]["verified"],
            "best": s["clears"]["best_verified"]["completion_input_tick"], "reference": arrival[mcell.TARGETS_TOTAL], "cap_jobs": s2["work"]["jobs"], "wall_jobs": s3["work"]["jobs"],
            "cells_cap": s4["archive"]["cells"], "children_checked": checked}


# =============================================================================================================================================


def main(argv: Sequence[str]) -> int:
    global LAB, FRONTIER
    args = list(argv[1:])
    for flag in ("--lab-root", "--frontier"):
        if flag in args:
            i = args.index(flag)
            if flag == "--lab-root":
                LAB = Path(args[i + 1])
            else:
                FRONTIER = Path(args[i + 1])
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
            extra = json.dumps(info, default=str, separators=(",", ":"))[:600] if info else ""
            print(f"PASS {name} ({time.perf_counter() - t0:.1f} s) {extra}", flush=True)
        except Exception as exc:  # noqa: BLE001 - reported per test
            print(f"FAIL {name} ({time.perf_counter() - t0:.1f} s): {type(exc).__name__}: {exc}"[:3000], flush=True)
            print(traceback.format_exc()[-2500:], flush=True)
        if g.LabGuard.installed:
            print(f"STOP: the lab guard is armed in the test process after {name}; the remaining tests cannot run here (an audit hook cannot be removed)", flush=True)
            break
    for p in CREATED:
        shutil.rmtree(p, ignore_errors=True)
    print(f"crossing search tests: {passed}/{len(pick)} passed in {time.perf_counter() - t_all:.0f} s")
    return 0 if passed == len(pick) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
