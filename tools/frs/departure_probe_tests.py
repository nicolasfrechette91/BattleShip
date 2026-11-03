#!/usr/bin/env python3
"""Zero-tick tests of the departure probe (tools/frs/departure_probe.py). No game process is started: synthetic traces (arbitrary group and
line ids, period, ticks and targets) stand in for the game in the derivation, candidate, band, verdict and engine checks; the real lab records
of the probed clear are read (never written) for the record checks; the command-line refusals run in child processes (the lab guard is an
audit hook and cannot be removed). The test process never arms the lab guard and writes only under temporary folders, which it removes.

    python -B tools/frs/departure_probe_tests.py                 every test
    python -B tools/frs/departure_probe_tests.py real            the real-record checks only (reads <lab root>)
    python -B tools/frs/departure_probe_tests.py stub            the synthetic checks only
    python -B tools/frs/departure_probe_tests.py only <name>     the tests whose name contains <name>
    ... [--lab-root DIR]                                         the lab root of the real-record checks (default C:/BattleShip_lab)
"""
from __future__ import annotations

import copy
import gzip
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tokenize
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RL = REPO / "rl"
sys.path.insert(0, str(RL))
sys.path.insert(0, str(HERE))

import departure_probe as dp  # noqa: E402
import frs_archive as fa  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_verify as fv  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_worker as mw  # noqa: E402

TESTS: List[Tuple[str, str, Callable[[], Optional[Dict[str, Any]]]]] = []
CREATED: List[Path] = []
LAB = Path(g.DEFAULT_LAB_ROOT)
_REAL: Dict[str, Any] = {}
CLF = mcell.Classifier()


def real(fn: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    TESTS.append(("real", fn.__name__, fn))
    return fn


def synthetic(fn: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    TESTS.append(("stub", fn.__name__, fn))
    return fn


def check(cond: Any, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def raises(fn: Callable[[], Any], exc: type, needle: str = "") -> str:
    try:
        fn()
    except exc as e:  # noqa: BLE001
        check(needle in str(e), f"expected {needle!r} in {e}")
        return str(e)
    raise AssertionError(f"{exc.__name__} not raised")


def tmpdir(tag: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=f"departure_probe_{tag}_"))
    CREATED.append(p)
    return p


# == the synthetic world =========================================================================================================================


class World:
    """A trace generator: one moving group (ids and lines chosen by the test) with a triangle-wave translation, a static group, a fighter that
    rides the group in contact intervals and leaves through a status run, ten targets broken at chosen ticks, a clear at the last tick."""

    def __init__(self, *, n: int = 600, gid: int = 5, glines: Sequence[int] = (7, 11), static_lines: Sequence[int] = (0, 1, 2, 3), P: int = 120,
                 bottom: int = 50, intervals: Sequence[Tuple[int, int, int, int]] = ((100, 120, 105, 112), (200, 330, 210, 310)), squat: int = 3,
                 breaks: Sequence[Tuple[int, int]] = ((30, 4), (70, 0), (150, 5), (180, 7), (260, 9), (400, 3), (450, 2), (500, 6), (550, 8),
                                                     (600, 1)), lo: float = 1000.0, hi: float = 2000.0, moving: bool = True, hover: Tuple[int, int] = (113, 118),
                 salt: int = 3):
        self.n, self.gid, self.glines, self.static_lines, self.P, self.bottom = n, gid, list(glines), list(static_lines), P, bottom
        self.intervals, self.squat, self.breaks, self.lo, self.hi, self.moving, self.hover = list(intervals), squat, list(breaks), lo, hi, moving, hover
        self.words = bytes((i * 7 + salt) % mcell.TRACK1_WORDS for i in range(n))

    def gy(self, t: int) -> float:
        if not self.moving:
            return self.lo
        ph, half = (t - self.bottom) % self.P, self.P // 2
        return self.lo + (self.hi - self.lo) * (ph / half if ph <= half else (self.P - ph) / half)

    def mask_at(self, t: int) -> int:
        m = (1 << 10) - 1
        for bt, i in self.breaks:
            if bt <= t:
                m &= ~(1 << i)
        return m

    def records_at(self, t: int) -> List[Dict[str, Any]]:
        by = {i: bt for bt, i in self.breaks}
        return [{"id": i, "break_input_tick": by[i] if by.get(i, 10 ** 9) <= t else 0, "animated": 0} for i in range(10)]

    def where(self, t: int) -> Tuple[int, bool, int]:
        """(floor line, grounded, status) of the base trajectory at tick t."""
        for k, (s, e, gs, ge) in enumerate(self.intervals):
            if s <= t <= e:
                line = self.glines[(len(self.intervals) - 1 - k) % len(self.glines)]
                if gs <= t <= ge:
                    return line, True, 20 if t > ge - self.squat else 10
                return line, False, 22
        return self.static_lines[1], True, 10

    def reply(self, t: int, *, line: int, ground: bool, status: int, x: float, vy: float = 0.0, mask: Optional[int] = None,
              records: Optional[List[Dict[str, Any]]] = None, state: int = mcell.STATE_WAITING, game_status: int = 1,
              y: Optional[float] = None) -> Dict[str, Any]:
        m = self.mask_at(t) if mask is None else mask
        o = {"observation_schema": 1, "host_frame": t + 64, "input_tick": t, "time_passed": max(0, t - 1), "game_status": game_status, "btt_active": 1,
             "targets_remaining": bin(m).count("1"), "fighter_valid": 1, "position_x": x,
             "position_y": y if y is not None else self.gy(t) + (0.0 if ground else 50.0),
             "air_velocity_x": 0.0 if ground else -3.0, "air_velocity_y": vy, "ground_velocity_x": 0.0, "facing_direction": 1,
             "ground_air_state": 0 if ground else 1, "fighter_status_id": status, "jumps_used": 0 if ground else 1}
        sp = {"fighter": {"floor_line_id": line, "valid": 1}, "groups": [{"id": 0, "translate": [0.0, 0.0]}, {"id": self.gid, "translate": [400.0, self.gy(t)]},
                                                                        {"id": 1, "translate": [0.0, 0.0]}],
              "target_live_mask": m, "target_positions": [[0.0, 0.0]] * 10}
        r = {"observation": o, "spatial": sp, "state": state, "step_count": t, "targets": {"records": records if records is not None else self.records_at(t)}}
        if t > 0:
            r.update({"consumed_tick": t - 1, "ok": True, "op": "step"})
        return r

    def base_reply(self, t: int) -> Dict[str, Any]:
        line, ground, status = self.where(t)
        x, y = 100.0 + t, None
        if self.hover[0] <= t <= self.hover[1]:
            x, y = 100.0 + self.hover[0], self.gy(self.hover[0]) + 50.0
        vy = 5.0 if (not ground and status == 22) else 0.0
        last = t == self.n
        return self.reply(t, line=line, ground=ground, status=status, x=x, vy=vy, y=y, state=mcell.STATE_ENDED if last else mcell.STATE_WAITING)

    def initial(self) -> Dict[str, Any]:
        r = self.base_reply(0)
        r["spatial"]["lines"] = ([{"id": ln, "group": 1, "vertices": [[0.0, 0.0], [10.0, 0.0]]} for ln in self.static_lines]
                                 + [{"id": ln, "group": self.gid, "vertices": [[50.0, 0.0], [-50.0, 0.0]]} for ln in self.glines])
        r["can_step"] = True
        return r

    def trace(self, steps: Sequence[Dict[str, Any]], words: bytes, label: str = "base", clear: bool = False) -> Dict[str, Any]:
        n = len(steps)
        tr = {"label": label, "extra_env": dict(fv.FLAGS_VERIFY), "initial": self.initial(), "steps": list(steps), "submitted": n, "unsent": len(words) - n,
              "consumed_tick_mismatch": None, "startup_s": 0.1, "stepping_s": 0.1, "action_digest": mcell.words_digest(bytes(words[:n])),
              "final_state": "EpisodeEnded" if clear else "WaitingForAction", "result": None}
        if clear:
            tr["result"] = {"outcome": "clear", "targets_broken": 10, "completion_input_tick": n, "completion_time_passed": n - 1}
        return tr

    def base_trace(self) -> Dict[str, Any]:
        return self.trace([self.base_reply(t) for t in range(1, self.n + 1)], self.words, clear=True)


def stub_analyse(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    br, _ = dp.native_breaks({"initial": initial, "steps": list(steps)})
    return {"breaks": [(i, t - 1) for t, i in br]}


def write_gz(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))


def add_clear(lab: Path, world: World, run: str = "synthrun", n: int = 1, cid: int = 2) -> Dict[str, Any]:
    """Append one VERIFIED clear row of `world` to <lab>/<run>/run/verifications.jsonl and write its two traces (r2 = r1, as a verified clear's)."""
    tr = world.base_trace()
    ev = fv.evaluate(tr, world.words, stub_analyse)
    check(ev["outcome"] == "clear", f"the synthetic base trace clears: {ev['outcome']}")
    rd = lab / run / "run"
    row = {"mode": "lab", "kind": "clear", "n": n, "cid": cid, "k": 0, "words": len(world.words), "words_hex": world.words.hex(),
           "words_digest": mcell.words_digest(world.words), "verdict": fv.VERIFIED, "completion_input_tick": ev["completion_input_tick"],
           "completion_time_passed": ev["completion_time_passed"], "chain_r1": ev["final_chain"], "chain_r2": ev["final_chain"], "breaks_r1": ev["breaks"],
           "breaks_r2": ev["breaks"], "claim": {"words_digest": mcell.words_digest(world.words), "completion_input_tick": ev["completion_input_tick"],
                                                "completion_time_passed": ev["completion_time_passed"], "chain": ev["final_chain"]}}
    rd.mkdir(parents=True, exist_ok=True)
    with open(rd / "verifications.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row) + "\n")
    write_gz(rd / "traces" / f"clear_n{n}_c{cid}_k0_r1.json.gz", tr)
    write_gz(rd / "traces" / f"clear_n{n}_c{cid}_k0_r2.json.gz", tr)
    return {"row": row, "trace": tr}


def synthetic_lab(world: World, root: Optional[Path] = None) -> Tuple[Path, Dict[str, Any]]:
    """A temporary lab root holding one verification row and its two traces."""
    lab = root or tmpdir("lab")
    return lab, add_clear(lab, world)


def synthetic_plan(world: World, params: Optional[dp.ProbeParams] = None) -> Dict[str, Any]:
    lab, info = synthetic_lab(world)
    clear = dp.load_clear(lab, "best", stub_analyse)
    P = dp.build_plan(clear, params or dp.ProbeParams(), CLF)
    return {"lab": lab, "clear": clear, "P": P, **info}


def thin(S: Mapping[str, Any], k: int) -> Dict[str, Any]:
    """A test-side subsample of the planned candidates (the tool itself has no reductions): the control's d and every k-th departure tick."""
    P = S["P"]
    D = P["plan"]["departure"]["D"]
    ds = sorted({c["d"] for c in P["candidates"]})
    keep = {D} | set(ds[::k])
    kept = [dict(c) for c in P["candidates"] if c["d"] in keep]
    for i, c in enumerate(kept):
        c["idx"] = i
    plan = dict(P["plan"], candidates=len(kept), ticks_planned=sum(c["ticks"] for c in kept))
    return dict(S, P=dict(P, candidates=kept, plan=plan))


# == synthetic tests ===============================================================================================================================


@synthetic
def derivation_is_generic_and_reads_the_record() -> Dict[str, Any]:
    """Arbitrary ids, period and ticks: the probe finds them from the record (two contact intervals, two lines in the moving group)."""
    w = World()
    S = synthetic_plan(w)
    p = S["P"]["plan"]
    check([gm["group"] for gm in p["groups"]] == [w.gid] and p["group_lines"] == sorted(w.glines), f"moving group {p['groups']}")
    ivs = p["contact_intervals"]
    check([(iv["start"], iv["end"]) for iv in ivs] == [(s, e) for s, e, _a, _b in w.intervals], f"intervals {ivs}")
    check(ivs[0]["still"] == w.hover[1] - w.hover[0] and ivs[0]["ride_or_still"] == (w.intervals[0][3] - w.intervals[0][2] + 1) + ivs[0]["still"],
          f"still / ride-or-still counts {ivs[0]}")
    check(p["chosen_interval"] == 1, "the interval with the largest ride-or-still count is probed")
    s, e, gs, ge = w.intervals[1]
    dep = p["departure"]
    check((dep["C0"], dep["F"], dep["C1"], dep["L"], dep["G"], dep["A"], dep["S"], dep["D"]) == (s, gs, e, e + 1, ge, ge + 1, ge - w.squat + 1, ge - w.squat),
          f"departure {dep}")
    check(dep["grounded_D"] and dep["floor_line_D"] in w.glines, "D is on the group, grounded")
    check(p["period"]["P"] == w.P and p["period"]["origin"] == w.bottom, f"period {p['period']}")
    B = next(t for t, _i in w.breaks if t > dep["D"])
    check(p["baseline"]["B"] == B and p["baseline"]["target"] == dict(w.breaks)[B], f"baseline {p['baseline']}")
    pr = p["progress_rule"]
    check(pr["baseline_mask"] == w.mask_at(B) and pr["baseline_live_targets"] == sorted(i for i in range(10) if w.mask_at(B) >> i & 1),
          f"the progress rule's mask is the baseline's at B {pr}")
    win = p["window"]
    check(win["earlier"] == [gs, dep["D"], dep["D"] - gs + 1] and win["later"] == [dep["D"] + 1, dep["D"] + w.P, w.P], f"window {win}")
    check(win["excluded_airborne_contact"] == [s, gs - 1, gs - s], "the airborne contact ticks before the first grounded tick are excluded")
    check(p["candidates"] == (dep["D"] - gs + 1 + w.P) * 2 and p["variants"]["K"] == 1, f"candidates {p['candidates']}")
    onb = [[t, i] for t, i in w.breaks if gs <= t <= dep["D"]]
    check(p["on_group_breaks"] == onb and len(onb) == 1, f"on-group breaks over [F, D] from the record {p['on_group_breaks']}")
    check(p["pre_break"]["d"] == [gs, onb[0][0] - 1, onb[0][0] - gs], f"pre-break departures {p['pre_break']}")
    for c in S["P"]["candidates"]:
        check(c["pre_break"] == (c["d"] < onb[0][0]) and (c["pending_on_group"] == onb) == c["pre_break"], f"{c['label']}: pre-break flag")
    # N1: a break during the airborne contact ticks before F is not an on-group break
    w2 = World(breaks=((30, 4), (70, 0), (150, 5), (s + 3, 7), (260, 9), (400, 3), (450, 2), (500, 6), (550, 8), (600, 1)))
    p2 = synthetic_plan(w2)["P"]["plan"]
    check(p2["on_group_breaks"] == [[260, 9]] and s <= s + 3 < gs, f"on-group breaks start at F, not C0: {p2['on_group_breaks']}")
    xr, sp = p["exit_run"], p["spans"]
    check(xr["ticks"] == e - ge and xr["all_airborne"] and xr["floor_lines"] == [w.glines[0]] and xr["at_L"]["floor_line_id"] not in w.glines,
          f"exit run {xr}")
    check(xr["at_C1"]["group_line_span"] == [350.0, 450.0] and xr["at_L"]["floor_line_span"] == [0.0, 10.0],
          f"line extents are the vertices plus the group's translation {xr['at_C1']['group_line_span']} {xr['at_L']['floor_line_span']}")
    check(sp["parts_sum"] == B - dep["D"] and sp["L"] == e + 1 and sp["landing"] == e + 1 and sp["parts"]["airborne_over_group"] == e + 1 - (ge + 1),
          f"spans {sp}")
    check(p["group_at"]["C0"]["phase"] == (s - w.bottom) % w.P, "phase from the measured origin")
    return {"D": dep["D"], "B": B, "P": w.P, "candidates": p["candidates"]}


@synthetic
def refusals_when_the_record_cannot_support_the_method() -> Dict[str, Any]:
    w = World()
    tr = w.base_trace()
    bad = copy.deepcopy(tr)
    del bad["initial"]["spatial"]["lines"]
    check(dp.required_field_problems(bad), "a missing line table is reported")
    bad2 = copy.deepcopy(tr)
    del bad2["steps"][10]["spatial"]["fighter"]["floor_line_id"]
    check(any("floor_line_id" in x for x in dp.required_field_problems(bad2)), "a missing floor line is reported")
    raises(lambda: dp.geometry(World(moving=False).base_trace()), dp.ProbeError, "non-static")
    flat = World(P=4000)                                   # a single half-cycle: no two turning points of one kind
    raises(lambda: dp.geometry(flat.base_trace()), dp.ProbeError, "no period")
    s, e, gs, ge = w.intervals[1]
    walk = World(intervals=(w.intervals[0], (s, e, gs, e)))       # grounded to the interval's last tick, grounded after: no airborne exit
    raises(lambda: dp.geometry(walk.base_trace()), dp.ProbeError, "no airborne exit")
    tail = World(intervals=(w.intervals[0], (s, w.n, gs, ge)))
    raises(lambda: dp.geometry(tail.base_trace()), dp.ProbeError, "no exit")
    # a missing field in the probed clear's verified trace stops the load (never substituted)
    lab, info = synthetic_lab(w)
    t1 = copy.deepcopy(info["trace"])
    del t1["steps"][5]["spatial"]["groups"]
    write_gz(lab / "synthrun" / "run" / "traces" / "clear_n1_c2_k0_r1.json.gz", t1)
    raises(lambda: dp.load_clear(lab, "best", stub_analyse), dp.ProbeError, "lacks fields")
    # r2 differing per tick from r1 stops the load
    lab2, info2 = synthetic_lab(World())
    t2 = copy.deepcopy(info2["trace"])
    t2["steps"][7]["observation"]["position_x"] += 1.0
    write_gz(lab2 / "synthrun" / "run" / "traces" / "clear_n1_c2_k0_r2.json.gz", t2)
    raises(lambda: dp.load_clear(lab2, "best", stub_analyse), dp.ProbeError, "disagree")
    return {"refusals": 8}


@synthetic
def window_and_order() -> Dict[str, Any]:
    w = World()
    S = synthetic_plan(w)
    geo, D = S["P"]["geo"], S["P"]["plan"]["departure"]["D"]
    full = dp.window_of(geo)
    check(full["rule"] == "full" and full["earlier"] == list(range(geo["departure"]["F"], D + 1))
          and full["later"] == list(range(D + 1, D + geo["period"]["P"] + 1)), "the full window only (no reductions)")
    check(not hasattr(dp.ProbeParams(), "stride") and not hasattr(dp.ProbeParams(), "half"), "the reductions are plan text, not options")
    for n in (1, 2, 7, 64, 300):
        o = dp.bit_reverse_order(n)
        check(sorted(o) == list(range(n)), f"the order is a permutation ({n})")
    o = dp.bit_reverse_order(64)
    check(set(o[:8]) == set(range(0, 64, 8)), "every prefix of the order spreads over the range")
    cands = S["P"]["candidates"]
    check(cands[0]["side"] == "control" and cands[0]["d"] == D and cands[0]["variant"] == dp.VARIANT_CLEAR, "the control is dispatched first")
    check(len({(c["d"], c["variant"]) for c in cands}) == len(cands), "each (d, variant) once")
    return {"full": len(full["earlier"]) + len(full["later"])}


@synthetic
def candidate_words_follow_the_method() -> Dict[str, Any]:
    w = World()
    S = synthetic_plan(w, dp.ProbeParams(variants=3, seed=7, budget_factor=1.5))
    p, cands = S["P"]["plan"], S["P"]["candidates"]
    D, B, E = p["departure"]["D"], p["baseline"]["B"], p["budget"]["E"]
    words = w.words
    check(E == math.ceil(1.5 * (B - D)) and E >= B - D, f"E {E}")
    draw = p["variants"]["draw_id"]
    check(draw.endswith("|departure|s7") and draw.startswith(mcell.words_digest(words)[:16]), f"the draw id records the seed {draw}")
    for c in cands:
        d, v, cw = c["d"], c["variant"], c["words"]
        prefix = words[:d] if d <= D else words[:D] + bytes([dp.NEUTRAL_WORD]) * (d - D)
        check(cw[:d] == prefix and len(cw) == d + E and c["words_digest"] == mcell.words_digest(cw), f"{c['label']}: prefix and length")
        if v == dp.VARIANT_CLEAR:
            check(cw[d:d + (B - D)] == words[D:B] and set(cw[d + (B - D):]) <= {dp.NEUTRAL_WORD}, f"{c['label']}: the clear's exit shifted to d")
        else:
            check(cw[d:] == fa.stream_words(draw, int(v[1:]), E), f"{c['label']}: the lab burst generator's keyed stream")
        check(c["prefix_ref"] == ("clear" if d <= D else "filler"), "prefix reference")
    ctl = cands[0]
    check(ctl["words"][:B] == words[:B], "the control replays the clear's own words to B")
    check(mcell.TRIPLES[dp.NEUTRAL_WORD] == (0, 0, 0), "the neutral word")
    S2 = synthetic_plan(World(), dp.ProbeParams(variants=3, seed=7, budget_factor=1.5))
    S3 = synthetic_plan(World(), dp.ProbeParams(variants=3, seed=8, budget_factor=1.5))
    check(S2["P"]["plan"]["candidate_set_digest"] == p["candidate_set_digest"] != S3["P"]["plan"]["candidate_set_digest"],
          "the candidate-set digest is deterministic and covers the seed")
    return {"candidates": len(cands), "E": E}


class Fake:
    """Candidate traces for the synthetic world: the base trajectory up to d (or, for later departures, up to D and then grounded filler on the
    group), then the exit: `hold` grounded ticks on the group (a later departure), a take-off status run of the world's squat length on the
    group, and a flight off it whose breaks are set by `break_at(d, variant)`: None, a tick (the baseline's target), (tick, [targets]) or a
    list of those. `stay` keeps the fighter on the group to the end (no departure); `errors` labels never start; `contract` labels carry a
    step_count break; `bad_control` sends the control through the exit path (so it does not reproduce B); from call `drift_from` on (0 = the
    first control), every replay raises the pin drift rl/frs_verify raises before launching when a pinned file changed."""

    def __init__(self, w: World, plan: Mapping[str, Any], break_at: Callable[[int, str], Any], *, filler_off: Optional[int] = None,
                 mismatch: Sequence[str] = (), clock: Optional["Clock"] = None, step_s: float = 1.0, fall: Sequence[str] = (),
                 hold: Optional[Mapping[Tuple[int, str], int]] = None, stay: Sequence[Tuple[int, str]] = (), errors: Sequence[str] = (),
                 contract: Sequence[str] = (), bad_control: bool = False, drift_from: Optional[int] = None):
        self.w, self.plan, self.break_at, self.filler_off = w, plan, break_at, filler_off
        self.mismatch, self.clock, self.step_s, self.fall = set(mismatch), clock, step_s, set(fall)
        self.hold, self.stay, self.errors, self.contract, self.bad_control = dict(hold or {}), set(stay), set(errors), set(contract), bad_control
        self.drift_from = drift_from
        self.D, self.B = int(plan["departure"]["D"]), int(plan["baseline"]["B"])
        self.target = int(plan["baseline"]["target"])
        self.base = [w.base_reply(t) for t in range(0, w.n + 1)]
        self.calls: List[str] = []
        self._lock = threading.Lock()

    def filler_reply(self, t: int) -> Dict[str, Any]:
        on = self.filler_off is None or t < self.filler_off
        return self.w.reply(t, line=self.w.glines[0] if on else self.w.static_lines[0], ground=on, status=10, x=100.0 + self.D,
                            mask=self.w.mask_at(self.D), records=self.w.records_at(self.D))

    def events(self, d: int, v: str) -> List[Tuple[int, List[int]]]:
        tb = self.break_at(d, v)
        if tb is None:
            return []
        if isinstance(tb, list):
            return [(int(t), list(ts)) for t, ts in tb]
        if isinstance(tb, tuple):
            return [(int(tb[0]), list(tb[1]))]
        return [(int(tb), [self.target])]

    def finish(self, tr: Dict[str, Any], label: str) -> Dict[str, Any]:
        if label in self.contract:
            tr["steps"][5] = dict(tr["steps"][5], step_count=tr["steps"][5]["step_count"] + 1)
        return tr

    def replay(self, words: bytes, label: str, slot: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.calls.append(label)
            k = len(self.calls) - 1
        if self.drift_from is not None and k >= self.drift_from:
            raise mw.MismatchError("pin_drift", {"problems": ["frozen BattleShip.exe differs from frozen_runtime.json"]})
        if self.clock is not None:
            self.clock.advance(self.step_s)
        if label.replace("_retry", "") in self.errors:
            raise RuntimeError(f"stub: {label} could not start")
        n = len(words)
        if label in ("control_clear_r1", "control_clear_r2"):
            steps = [copy.deepcopy(r) for r in self.base[1:n + 1]]
            if label.replace("control_", "") in self.mismatch:
                steps[3]["observation"]["position_x"] += 0.5
            return self.w.trace(steps, words, label, clear=n == self.w.n)
        if label == "control_filler":
            steps = [self.base[t] for t in range(1, self.D + 1)] + [self.filler_reply(t) for t in range(self.D + 1, n + 1)]
            return self.w.trace(steps, words, label)
        d, v = int(label[1:6]), label.split("_")[1]
        if d == self.D and v == dp.VARIANT_CLEAR and not self.bad_control:
            return self.finish(self.w.trace([self.base[t] for t in range(1, n + 1)], words, label), label)
        pre = [self.base[t] if t <= self.D else self.filler_reply(t) for t in range(1, d + 1)]
        if label in self.mismatch:
            pre[0] = copy.deepcopy(pre[0])
            pre[0]["observation"]["position_x"] += 0.25
        ev = self.events(d, v)
        m0 = pre[-1]["spatial"]["target_live_mask"]
        rec0 = pre[-1]["targets"]["records"]
        line = pre[-1]["spatial"]["fighter"]["floor_line_id"]
        hold, stay = self.hold.get((d, v), 0), (d, v) in self.stay
        post = []
        for t in range(d + 1, n + 1):
            m, rec = m0, [dict(r) for r in rec0]
            for tb, ts in ev:
                if t >= tb:
                    for i in ts:
                        m &= ~(1 << i)
                    rec = [dict(r, break_input_tick=tb) if int(r["id"]) in ts else r for r in rec]
            k = t - d
            if stay or k <= hold:
                post.append(self.w.reply(t, line=line, ground=True, status=10, x=100.0 + d, mask=m, records=rec))
            elif k <= hold + self.w.squat:
                post.append(self.w.reply(t, line=line, ground=True, status=20, x=100.0 + d, mask=m, records=rec))
            else:
                fall = label in self.fall and t == n
                post.append(self.w.reply(t, line=self.w.static_lines[2], ground=False, status=22, x=50.0 - t, vy=-2.0, mask=m, records=rec,
                                         game_status=mcell.GAME_STATUS_END if fall else 1))
        return self.finish(self.w.trace(pre + post, words, label), label)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self.t

    def advance(self, s: float) -> None:
        with self._lock:
            self.t += s


def ctx_of(S: Mapping[str, Any], fake: Fake, band: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    D, P = S["P"]["plan"]["departure"]["D"], S["P"]["plan"]["period"]["P"]
    filler = fake.replay(bytes(S["clear"]["words"][:D]) + bytes([dp.NEUTRAL_WORD]) * P, "control_filler", 0)
    return {"geo": S["P"]["geo"], "baseline": S["P"]["baseline"], "ref_chain": {"clear": S["clear"]["chain"], "filler": dp.chain_list(filler)},
            "clf": CLF, "d_info": S["P"]["d_info"], "band": band}


def cand_of(S: Mapping[str, Any], d: int, v: str) -> Dict[str, Any]:
    return next(c for c in S["P"]["candidates"] if c["d"] == d and c["variant"] == v)


def band_around(S: Mapping[str, Any], half: int = 10) -> Dict[str, Any]:
    """A test band of 2 x half + 1 phases centred on the probed clear's departure phase."""
    Pp = S["P"]["plan"]["period"]["P"]
    phD = dp.phase_of(S["P"]["plan"]["departure"]["D"], S["P"]["geo"]["period"])
    return {"arc": {"start": (phD - half) % Pp, "length": 2 * half}, "P": Pp, "rule": "test", "sources": 1, "axis_value_range": None, "directions": [-1],
            "onsets": [], "digest": "0" * 64}


@synthetic
def reading_a_candidate() -> Dict[str, Any]:
    w = World()
    S = synthetic_plan(w)
    p = S["P"]["plan"]
    D, B = p["departure"]["D"], p["baseline"]["B"]
    per = S["P"]["geo"]["period"]
    on_line = next(t for t, _i in w.breaks if w.intervals[1][2] <= t <= D)          # the break taken while riding the group
    on_target = next(i for t, i in w.breaks if t == on_line)
    other = next(i for i in range(10) if p["baseline"]["mask"] >> i & 1)         # a target the baseline still had live at B
    plan_breaks = {(on_line + 5, "a"): B - 10, (D - 3, "a"): B - 7, (D + 4, "a"): B + 20,
                   (on_line - 6, "a"): B - 50, (on_line - 8, "a"): (B - 30, [on_target, int(p["baseline"]["target"])]),
                   (on_line - 10, "a"): (B - 40, [on_target]), (on_line + 7, "a"): [(B - 20, [other]), (B - 12, [p["baseline"]["target"]])],
                   (D - 5, "a"): B - 9}
    fake = Fake(w, p, lambda d, v: plan_breaks.get((d, v)), mismatch=(f"d{D - 2:05d}_a",), fall=(f"d{D - 1:05d}_g1",),
                hold={(D - 5, "a"): 6}, stay=[(D - 6, "g1")])
    band = band_around(S)
    ctx = ctx_of(S, fake, band)
    rd = lambda d, v: dp.read_candidate(fake.replay(cand_of(S, d, v)["words"], cand_of(S, d, v)["label"], 0), cand_of(S, d, v), ctx)  # noqa: E731
    ctl = rd(D, "a")
    check(ctl["valid"] and ctl["prefix_equal"] and ctl["chain_at_B_equal"] and ctl["first_break"]["tick"] == B and not ctl["beats_B"], f"control {ctl}")
    check(ctl["first_break"]["same_as_baseline_next"] and ctl["comparable"] and ctl["progress_tick"] == B, "the control is the baseline's own next break")
    check(ctl["departed_at_d"] and ctl["departure_tick"] == D and ctl["departure_phase"] == dp.phase_of(D, per) and ctl["in_band"] is True
          and ctl["floor_line_leave_tick"] == w.intervals[1][1] + 1 and ctl["floor_line_leave_phase"] == dp.phase_of(w.intervals[1][1], per),
          f"S2: the control's measured departure is D, its floor-line leave is reported apart {ctl['departure_tick']} {ctl['floor_line_leave_tick']}")
    a = rd(on_line + 5, "a")
    check(a["valid"] and a["beats_B"] and a["gain"] == 10 and a["comparable"] and a["first_break"]["exit_ticks"] == B - 10 - (on_line + 5), f"beats {a}")
    check(a["departed_at_d"] and a["departure_tick"] == on_line + 5 and a["departure"]["S"] == on_line + 6, "the exit's onset is d")
    check(a["end_state"]["grounded"] is False and "helpless" in a["end_state"] and a["end_state"]["status"] == 22, "the end state at the break")
    check(not a["pre_break"] and a["pending_on_group"] == [], "a departure after the on-group break is not pre-break")
    # D1: another target first, then the baseline's target, before B: the progress tick decides
    o = rd(on_line + 7, "a")
    check(o["first_break"]["tick"] == B - 20 and o["first_break"]["target"] == other and not o["first_break"]["same_as_baseline_next"]
          and not o["comparable"] and o["progress_tick"] == B - 12 and o["beats_B"] and o["gain"] == 12
          and o["progress_targets"] == [p["baseline"]["target"]], f"D1: progress in any order beats B {o}")
    before = rd(on_line - 4, "a")
    check(before["valid"] and before["pre_break"] and before["first_break"] is None and before["progress_tick"] is None and not before["beats_B"],
          "no break within the budget")
    less = rd(on_line - 6, "a")
    check(less["pre_break"] and less["earlier_than_B"] and not less["comparable"] and less["progress_tick"] is None and not less["beats_B"]
          and less["gain"] is None, f"an earlier break that leaves the on-group target live has no progress, never faster: {less}")
    both = rd(on_line - 8, "a")
    check(both["pre_break"] and both["earlier_than_B"] and both["comparable"] and both["progress_tick"] == B - 30 and both["beats_B"]
          and both["gain"] == 30 and both["departed_at_d"] and both["first_break"]["on_group_target"]
          and sorted(both["first_break"]["targets_at_tick"]) == sorted([on_target, fake.target]),
          f"D2: a pre-break departure that reaches the baseline's progress before B is counted, labelled pre-break: {both}")
    ong = rd(on_line - 10, "a")
    check(ong["pre_break"] and ong["first_break"]["target"] == on_target and ong["first_break"]["on_group_target"]
          and not ong["first_break"]["same_as_baseline_next"] and not ong["beats_B"], f"which break a pre-break departure reaches first: {ong['first_break']}")
    later = rd(D + 4, "a")
    check(later["valid"] and later["first_break"]["tick"] == B + 20 and not later["earlier_than_B"] and later["prefix_ref"] == "filler"
          and later["departed_at_d"] and later["in_band"] is True and not later["beats_B"], f"later {later}")
    # S3: a candidate that does not depart at d
    held = rd(D - 5, "a")
    check(held["valid"] and not held["departed_at_d"] and held["departure_tick"] == D + 1 and held["departure_reason"] == "later"
          and held["departure_phase"] == dp.phase_of(D + 1, per) and held["beats_B"],
          f"held on the group 6 ticks: departs at d + 6, reported as not departing at d {held}")
    stay = rd(D - 6, "g1")
    check(stay["valid"] and not stay["departed_at_d"] and stay["departure_tick"] is None and stay["departure_reason"] == "no_exit"
          and stay["in_band"] is None and stay["floor_line_leave_tick"] is None, f"never leaves the group {stay}")
    mm = rd(D - 2, "a")
    check(mm["outcome"] == "mismatch" and mm["failed"] and not mm["valid"] and mm["mismatch_first_tick"] == 1, f"a prefix mismatch {mm}")
    fl = rd(D - 1, "g1")
    check(fl["outcome"] == "fall" and fl["valid"], f"a fall is an outcome, not a failure {fl['outcome']}")
    c3 = cand_of(S, D - 3, "a")
    tr = copy.deepcopy(fake.replay(c3["words"], c3["label"], 0))
    tr["steps"][20]["consumed_tick"] = 99
    bad = dp.read_candidate(tr, c3, ctx)
    check(bad["outcome"] == "contract" and bad["failed"] and bad["contract"]["tick"]["step"] == 20, f"a consumed-tick violation {bad.get('contract')}")
    tr1 = copy.deepcopy(fake.replay(c3["words"], c3["label"], 0))
    tr1["steps"][30]["step_count"] = 7
    check(dp.read_candidate(tr1, c3, ctx)["outcome"] == "contract", "a step_count violation is a contract failure (fv.evaluate does not check it)")
    tr2 = copy.deepcopy(fake.replay(c3["words"], c3["label"], 0))
    tr2["action_digest"] = "0" * 64
    check(dp.read_candidate(tr2, c3, ctx)["outcome"] == "contract", "an action-digest mismatch is a contract failure")
    tr3 = copy.deepcopy(fake.replay(cand_of(S, D - 2, "a")["words"], cand_of(S, D - 2, "a")["label"], 0))
    tr3["consumed_tick_mismatch"] = {"index": 4}
    check(dp.read_candidate(tr3, cand_of(S, D - 2, "a"), ctx)["outcome"] == "contract", "the contract is read before the prefix digest")
    err = dp.read_candidate(None, c3, ctx, ["boom"])
    check(err["outcome"] == "error" and err["failed"], "a replay that could not run")
    return {"B": B, "beat_gain": a["gain"], "pre_break_gain": both["gain"]}


def mk_row(d: int, *, in_band: bool, tick: Optional[int], progress: Any = "first", B: int = 100, failed: bool = False, variant: str = "a",
           pre_break: bool = False, target: int = 3, side: str = "earlier", departed: bool = True, reason: str = "later") -> Dict[str, Any]:
    """A results row: first break at `tick`; progress tick = tick by default (the first break leaves the baseline's progress), or as given."""
    r: Dict[str, Any] = {"d": d, "variant": variant, "side": side, "valid": not failed, "failed": failed, "d_phase": d % 50, "pre_break": pre_break,
                         "label": f"d{d:05d}_{variant}"}
    if failed:
        r["outcome"] = "error"
        return r
    prog = tick if progress == "first" else progress
    beats = prog is not None and prog < B
    r.update(departed_at_d=departed, departure_reason="at_d" if departed else reason, departure_tick=d if departed else d + 5,
             departure_phase=d % 50, in_band=in_band, progress_tick=prog, beats_B=beats, gain=B - prog if beats else None)
    if tick is None:
        r.update(first_break=None, earlier_than_B=False, comparable=None)
    else:
        r.update(first_break={"tick": tick, "target": target, "on_group_target": pre_break and target != 3, "same_as_baseline_next": target == 3},
                 comparable=prog == tick, earlier_than_B=tick < B, end_state={"grounded": False})
    return r


@synthetic
def verdict_rules() -> Dict[str, Any]:
    B = 100
    base = [mk_row(1, in_band=True, tick=B), mk_row(2, in_band=False, tick=None, side="later"), mk_row(3, in_band=False, tick=B + 5)]
    v = dp.verdict_of(base + [mk_row(4, in_band=False, tick=B - 9), mk_row(5, in_band=False, tick=B - 3)], 5, "COMPLETED", B, True)
    check(v["verdict"] == dp.NOT_FORCED and v["best"]["gain"] == 9 and v["best"]["d"] == 4 and v["d_beating_B_outside_band"] == 2, f"not forced {v}")
    v = dp.verdict_of(base + [mk_row(4, in_band=False, tick=B - 9, progress=None)], 4, "COMPLETED", B, True)
    check(v["verdict"] == dp.FORCED_IN_PROBE and v["earlier_with_less_progress"] == 1, f"forced (less progress is never faster) {v}")
    v = dp.verdict_of(base + [mk_row(4, in_band=False, tick=B - 9, progress=B + 2)], 4, "COMPLETED", B, True)
    check(v["verdict"] == dp.FORCED_IN_PROBE and v["outside_band_earlier_less_progress"] == 1, f"D1: the progress tick at or after B never beats B {v}")
    v = dp.verdict_of(base + [mk_row(6, in_band=False, tick=B - 20, progress=B - 12)], 4, "COMPLETED", B, True)
    check(v["verdict"] == dp.NOT_FORCED and v["best"]["gain"] == 12 and v["best"]["progress_tick"] == B - 12, f"D1: the progress tick decides {v}")
    v = dp.verdict_of(base, 3, "COMPLETED", B, True)
    check(v["verdict"] == dp.FORCED_IN_PROBE and v["outside_band_no_break"] == 1 and v["outside_band_later_break"] == 1, f"forced {v}")
    v = dp.verdict_of(base + [mk_row(4, in_band=True, tick=B - 2)], 4, "COMPLETED", B, True)
    check(v["verdict"] == dp.IN_BAND_GAIN and v["best"]["in_band"] is True, f"in-band gain {v}")
    # D2: a pre-break departure that reaches the baseline's progress before B counts (labelled), one without it does not
    pre = [mk_row(40, in_band=False, tick=B - 20, pre_break=True), mk_row(41, in_band=False, tick=B - 25, progress=None, pre_break=True, target=9),
           mk_row(42, in_band=True, tick=None, pre_break=True)]
    v = dp.verdict_of(base + pre, 6, "COMPLETED", B, True)
    pb = v["pre_break"]
    check(v["verdict"] == dp.NOT_FORCED and v["beats_B"] == 1 and v["beats_B_pre_break"] == 1 and v["beats_B_outside_band_pre_break"] == 1
          and v["best"]["pre_break"] is True and "pre-break" in v["reasons"][0], f"D2: a pre-break gain is counted and labelled {v}")
    check(pb["valid"] == 3 and pb["departed_at_d"] == 3 and pb["outside_band"] == 2 and pb["beats_B"] == 1 and pb["counted_as_gain"] == 1
          and pb["earlier_than_B"] == 2 and pb["first_break_by_target"]["9"]["on_group_target"] == 1
          and pb["first_break_by_target"]["3"]["earliest_tick"] == B - 20 and pb["first_break_by_target"]["none"]["candidates"] == 1,
          f"the pre-break counts {pb}")
    v = dp.verdict_of([mk_row(1, in_band=True, tick=B)] + pre[1:], 3, "COMPLETED", B, True)
    check(v["verdict"] == dp.FORCED_IN_PROBE and v["sides"]["which"] == "earlier side only" and v["sides"]["earlier_pre_break"] == 1,
          f"D2: pre-break departures outside the band test the earlier side {v['sides']}")
    # S3: rows that did not depart at d are reported apart and never counted
    nd = mk_row(7, in_band=False, tick=B - 30, departed=False, reason="later")
    v = dp.verdict_of(base + [nd, mk_row(8, in_band=False, tick=None, departed=False, reason="no_exit", pre_break=True)], 5, "COMPLETED", B, True)
    check(v["verdict"] == dp.FORCED_IN_PROBE and v["beats_B"] == 0 and v["counted"] == 3 and v["did_not_depart_at_d"]["rows"] == 2
          and v["did_not_depart_at_d"]["pre_break"] == 1 and v["did_not_depart_at_d"]["by_reason"] == {"later": 1, "no_exit": 1}
          and v["pre_break"]["did_not_depart_at_d"] == 1, f"S3: not departing at d is never counted {v}")
    v = dp.verdict_of([mk_row(1, in_band=True, tick=B), nd], 2, "COMPLETED", B, True)
    check(v["verdict"] == dp.INCONCLUSIVE and any("did not depart at d" in x for x in v["reasons"]), "S3: no counted outside row, no verdict")
    # S1: which sides of the band were tested
    s_both = dp.verdict_of(base, 3, "COMPLETED", B, True)["sides"]
    check(s_both["which"] == "both sides" and s_both["earlier"] == 1 and s_both["later"] == 1, f"both sides {s_both}")
    v = dp.verdict_of([mk_row(1, in_band=True, tick=B), mk_row(2, in_band=False, tick=None, side="later")], 2, "COMPLETED", B, True)
    line = dp.verdict_line(v)
    check(v["verdict"] == dp.FORCED_IN_PROBE and v["sides"]["which"] == "later side only" and "later side only" in v["reasons"][-1]
          and "later side only" in line and "Pre-break departures: valid 0" in line, f"S1: the later side only, stated automatically: {line}")
    v = dp.verdict_of([mk_row(1, in_band=True, tick=B), mk_row(3, in_band=False, tick=B + 5)], 2, "COMPLETED", B, True)
    check(v["sides"]["which"] == "earlier side only" and "earlier side only" in dp.verdict_line(v), "S1: the earlier side only")
    v = dp.verdict_of(base + pre, 6, "COMPLETED", B, True)
    line = dp.verdict_line(v)
    check("earlier side 3, of them pre-break 2; later side 1" in line and "beat B 1 (counted, labelled pre-break)" in line,
          f"S1: the side counts and the pre-break counts next to the verdict: {line}")
    # incomplete runs
    v = dp.verdict_of(base, 3, "PARTIAL", B, True)
    check(v["verdict"] == dp.INCONCLUSIVE, "a partial run is inconclusive")
    v = dp.verdict_of(base, 4, "COMPLETED", B, True)
    check(v["verdict"] == dp.INCONCLUSIVE and any("did not run" in x for x in v["reasons"]), "an incomplete window is inconclusive")
    rows = base + [mk_row(10 + i, in_band=False, tick=None) for i in range(6)] + [mk_row(30, in_band=False, tick=None, failed=True)]
    check(dp.verdict_of(rows, 10, "COMPLETED", B, True)["verdict"] == dp.FORCED_IN_PROBE, "exactly 10 % failed is still conclusive")
    rows2 = rows + [mk_row(31, in_band=False, tick=None, failed=True)]
    check(dp.verdict_of(rows2, 10, "COMPLETED", B, True)["verdict"] == dp.INCONCLUSIVE, "more than 10 % failed is inconclusive")
    check(dp.verdict_of(base, 3, "COMPLETED", B, False)["verdict"] == dp.INCONCLUSIVE, "no band, no verdict")
    v = dp.verdict_of([mk_row(1, in_band=True, tick=B)], 1, "COMPLETED", B, True)
    check(v["verdict"] == dp.INCONCLUSIVE and v["sides"]["which"] == "neither side", "nothing tested outside the band")
    rows_c = base + [mk_row(1, in_band=True, tick=B - 1, variant="g1"), mk_row(1, in_band=True, tick=None, variant="g2")] + pre + [nd]
    cbt = dp.curve_by_type(rows_c)
    check(cbt["clear_exit"]["1"] == B and cbt["generic"]["1"] == B - 1 and cbt["clear_exit"]["2"] is None and "7" not in cbt["clear_exit"],
          f"curve by type (counted rows only) {cbt}")
    check(cbt["pre_break_clear_exit"]["40"] == B - 20 and "40" not in cbt["clear_exit"], "the pre-break departures are their own part of the curve")
    pg = dp.curve_by_type(base + [mk_row(6, in_band=False, tick=B - 20, progress=B - 12)], "progress")
    check(pg["clear_exit"]["6"] == B - 12, f"the progress curve {pg}")
    csv = dp.curve_csv(base + pre + [nd])
    check(csv.count("\n") == 8 and csv.startswith("d,variant,") and csv.count(",pre_break,") == 3 and ",departed_at_d," in csv.splitlines()[0]
          and ",progress_tick," in csv.splitlines()[0] and "floor_line_leave_tick" in csv.splitlines()[0], "curve.csv labels the pre-break part")
    return {"rules": 20}


@synthetic
def band_arc() -> Dict[str, Any]:
    P = 300
    a = dp.arc_of([77, 101, 177], P)
    check((a["start"], a["length"]) == (77, 100) and dp.in_arc(120, a, P) and not dp.in_arc(178, a, P) and not dp.in_arc(76, a, P), f"arc {a}")
    b = dp.arc_of([290, 10, 5], P)
    check((b["start"], b["length"]) == (290, 20) and dp.in_arc(0, b, P) and dp.in_arc(295, b, P) and not dp.in_arc(11, b, P), f"wrapping arc {b}")
    c = dp.arc_of([42], P)
    check(c["length"] == 0 and dp.in_arc(42, c, P) and not dp.in_arc(43, c, P), "a single phase")
    raises(lambda: dp.arc_of([], P), dp.ProbeError, "no phase")
    return {"arcs": 3}


@synthetic
def band_of_reads_the_verified_clears() -> Dict[str, Any]:
    """N2 / N4: band_of on a synthetic lab with distinct departures (group 5, lines 7 and 11, period 120): rows with D, phase, G, S, status_G
    and G - D; a wrapping arc; a duplicate trajectory counted once; a clear that never uses the group and one with another period skipped;
    the band digest; a source that is not a verified clear refused."""
    wa = World()                                                                           # the probed clear: D 307, phase 17, G - D 3
    lab, _ = synthetic_lab(wa)
    wb = World(intervals=((100, 120, 105, 112), (200, 330, 210, 290)), salt=5)           # D 287, phase 117
    wc = World(intervals=((100, 120, 105, 112), (200, 330, 210, 322)), squat=5, salt=11)  # D 317, phase 27, G - D 5
    wd = World(P=100, salt=13)                                                             # another period: skipped
    we = World(moving=False, salt=17)                                                      # no moving group: skipped
    for k, w in enumerate((wb, wc, wd, we)):
        add_clear(lab, w, run="bandrun", n=10 + k, cid=20 + k)
    tdir = lab / "bandrun" / "run" / "traces"
    shutil.copy(tdir / "clear_n10_c20_k0_r1.json.gz", tdir / "copy_of_b_r1.json.gz")      # the same trajectory under another name
    write_gz(tdir / "unverified_r1.json.gz", World(salt=19).base_trace())                 # no VERIFIED row carries its digest: not a source
    clear = dp.load_clear(lab, "synthrun:1:2", stub_analyse)
    P = dp.build_plan(clear, dp.ProbeParams(), CLF)
    band = dp.band_of(lab, P["plan"], P["geo"], stub_analyse)
    per = P["geo"]["period"]
    own = band["own"]
    check((own["D"], own["phase"], own["G"], own["S"], own["status_G"], own["G_minus_D"]) == (307, (307 - wa.bottom) % wa.P, 310, 308, 20, 3),
          f"the probed clear's own row {own}")
    rows = {r["source"].split(":")[1]: r for r in band["rows"]}
    rb, rc = rows["clear_n10_c20_k0_r1.json.gz"], rows["clear_n11_c21_k0_r1.json.gz"]
    check((rb["D"], rb["phase"], rb["G"], rb["S"], rb["G_minus_D"]) == (287, (287 - wb.bottom) % wb.P, 290, 288, 3), f"row b {rb}")
    check((rc["D"], rc["phase"], rc["G"], rc["S"], rc["status_G"], rc["G_minus_D"]) == (317, (317 - wc.bottom) % wc.P, 322, 318, 20, 5), f"row c {rc}")
    check(band["sources"] == 2 and len(band["rows"]) == 2 and "copy_of_b_r1.json.gz" not in rows, f"a duplicate trajectory is counted once {sorted(rows)}")
    why = sorted(x["why"][:30] for x in band["skipped"])
    check(len(band["skipped"]) == 2 and any("period 100" in x["why"] for x in band["skipped"]) and any("non-static" in x["why"] for x in band["skipped"]),
          f"skipped {why}")
    phases = sorted({own["phase"], rb["phase"], rc["phase"]})
    check(band["arc"] == dp.arc_of(phases, wa.P) and (band["arc"]["start"], band["arc"]["length"]) == (rb["phase"], (own["phase"] - rb["phase"]) % wa.P + 10)
          and dp.in_arc(0, band["arc"], wa.P) and not dp.in_arc(rc["phase"] + 1, band["arc"], wa.P), f"the wrapping arc {band['arc']}")
    check(per["P"] == wa.P and band["onsets"] == [{"status_G": 20, "G_minus_D": 3, "rows": 2}, {"status_G": 20, "G_minus_D": 5, "rows": 1}],
          f"onsets {band['onsets']}")
    again = dp.band_of(lab, P["plan"], P["geo"], stub_analyse)
    check(again["digest"] == band["digest"] == dp.band_digest(band) and len(band["digest"]) == 64, "the band digest is deterministic")
    add_clear(lab, World(intervals=((100, 120, 105, 112), (200, 330, 210, 300)), salt=23), run="bandrun", n=30, cid=40)
    check(dp.band_of(lab, P["plan"], P["geo"], stub_analyse)["digest"] != band["digest"], "a new source changes the band digest")
    # a band source that carries a VERIFIED digest but is not a verified clear's trace is refused
    t = json.loads(gzip.open(tdir / "clear_n11_c21_k0_r1.json.gz", "rt", encoding="utf-8").read())
    t["extra_env"] = {}
    write_gz(tdir / "clear_n11_c21_k0_r1.json.gz", t)
    raises(lambda: dp.band_of(lab, P["plan"], P["geo"], stub_analyse), dp.ProbeError, "not a verified clear")
    t["extra_env"] = dict(fv.FLAGS_VERIFY)
    t["result"] = dict(t["result"], completion_input_tick=t["result"]["completion_input_tick"] - 1)
    write_gz(tdir / "clear_n11_c21_k0_r1.json.gz", t)
    raises(lambda: dp.band_of(lab, P["plan"], P["geo"], stub_analyse), dp.ProbeError, "differs from the VERIFIED row")
    return {"arc": band["arc"], "rows": len(band["rows"]), "digest": band["digest"][:16]}


def engine(w: World, S: Mapping[str, Any], fake: Fake, *, band: Optional[Mapping[str, Any]], clock: Clock, max_wall_s: float = 2700.0,
           ready: bool = True, run_name: str = "run", save: bool = False) -> Tuple[int, Dict[str, Any], Path]:
    lab = S["lab"]
    out = lab / "departure_probe_test"
    run_dir = out / run_name
    env = fr.LabEnv(worker_spec=lambda rank: {}, replay=fake.replay, analyse=stub_analyse,
                    readiness=(lambda: {"ok": True, "problems": []}) if ready else (lambda: {"ok": False, "problems": ["test refusal"]}),
                    battleship_pids=lambda: [], snapshot=lambda: None, import_problems=lambda: [], wait_no_battleship=lambda t: [],
                    code_manifest=lambda: {}, backend="stub", now=clock.now, log=lambda s: None, sample_s=0.2, row_every_s=0.5)
    cfg = dp.ProbeConfig(lab_root=lab, out=out, run_dir=run_dir, slots=3, max_wall_s=max_wall_s, stop_reserve_s=0.0, progress_every_s=5.0, save_traces=save,
                         head="f" * 40)
    code = dp.Probe(cfg, env, S["clear"], S["P"], band, CLF, {"available": False}).run()
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8")) if (run_dir / "summary.json").is_file() else {}
    return code, s, run_dir


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()] if p.is_file() else []


@synthetic
def engine_end_to_end() -> Dict[str, Any]:
    w = World()
    S = thin(synthetic_plan(w), 8)
    p = S["P"]["plan"]
    D, B = p["departure"]["D"], p["baseline"]["B"]
    band = band_around(S)
    shift = lambda d, v: (d + (B - D)) if v == dp.VARIANT_CLEAR else None  # noqa: E731
    clock = Clock()
    cands = S["P"]["candidates"]
    earlier = [c["label"] for c in cands if c["side"] == "earlier"]
    later_g = [(c["d"], c["variant"]) for c in cands if c["side"] == "later" and c["variant"] != dp.VARIANT_CLEAR and c["d"] <= D + 49]
    fake = Fake(w, p, shift, clock=clock, filler_off=D + 50, mismatch=earlier[2:4], hold={later_g[0]: 4}, stay=[later_g[1]])
    code, s, run_dir = engine(w, S, fake, band=band, clock=clock, save=True)
    rows = read_jsonl(run_dir / "results.jsonl")
    nd = read_jsonl(run_dir / "not_dispatched.jsonl")
    check(code == 0 and s["status"] == "COMPLETED", f"status {s.get('status')} {s.get('stop')}")
    check(s["controls"]["clear"]["verdict"] == fv.VERIFIED and all(s["controls"]["clear"]["per_tick_chain_equal"].values())
          and all(s["controls"]["clear"]["tick_contract_ok"].values()), "the clear replays twice exactly")
    check(s["later_max_d"] == D + 49 and nd and all(x["d"] > D + 49 for x in nd), f"the filler truncates the later window {s['later_max_d']}")
    lc = s["later_cut"]
    check(lc["filler_first_tick_off_group"] == D + 50 and lc["later_max_d"] == D + 49 and lc["cut"] and lc["later_dispatched_d"] < lc["later_planned_d"]
          and "complete" in lc["counted_as"], f"the measured cut point is reported and counted as complete {lc}")
    v = s["verdict"]
    check(v["did_not_depart_at_d"]["rows"] == 2 and v["did_not_depart_at_d"]["by_reason"] == {"later": 1, "no_exit": 1}
          and v["counted"] == v["valid"] - 2, f"S3: the held and the staying candidates are reported apart {v['did_not_depart_at_d']}")
    pbs = v["pre_break"]
    check(pbs["valid"] > 0 and pbs["beats_B"] == 0 and v["beats_B"] == sum(1 for r in rows if r.get("beats_B") and r.get("departed_at_d"))
          and not any(r.get("beats_B") for r in rows if r.get("pre_break")), f"pre-break rows without the on-group target never beat B {pbs}")
    rep = (run_dir / "report.md").read_text(encoding="utf-8")
    check("Pre-break departures" in rep and ",pre_break," in (run_dir / "curve.csv").read_text(encoding="utf-8") and "both sides of the band tested" in rep
          and "HEAD `" + "f" * 40 + "`" in rep and s["git"]["head"] == "f" * 40, "the report and the curve carry the pre-break part, the sides and HEAD")
    check(len(rows) == p["candidates"] - len(nd) == s["planned_after_filler"], f"every dispatched candidate returned {len(rows)}")
    check(s["counters"]["mismatches"] == 2 and sum(1 for r in rows if r["outcome"] == "mismatch") == 2, "two mismatches retired, the run continued")
    check(v["verdict"] == dp.NOT_FORCED and v["best"]["in_band"] is False and v["best"]["gain"] > 0 and v["sides"]["which"] == "both sides", f"verdict {v}")
    ctl = next(r for r in rows if r["side"] == "control")
    check(ctl["first_break"]["tick"] == B and ctl["chain_at_B_equal"] and ctl["departed_at_d"], "the in-run control reproduces B")
    for f in ("plan.json",):
        check(not (run_dir.parent / f).exists(), "the engine writes no plan (the command does)")
    for f in ("config.json", "controls.json", "results.jsonl", "summary.json", "report.md", "curve.csv", "run_log.jsonl"):
        check((run_dir / f).is_file(), f"{f} written")
    check(json.loads((run_dir / "config.json").read_text(encoding="utf-8"))["head_checked"] == "f" * 40, "config.json records the HEAD checked")
    check((run_dir / "traces" / f"{ctl['label']}.json.gz").is_file() and (run_dir / "traces" / "control_filler.json.gz").is_file(), "traces saved")
    check(report_ok(rep), "report.md")
    # three mismatches abort the run
    clock3 = Clock()
    fake3 = Fake(w, p, shift, clock=clock3, mismatch=earlier[4:7])
    code3, s3, _ = engine(w, S, fake3, band=band, clock=clock3, run_name="run_abort")
    check(code3 == 3 and s3["status"] == "ABORTED" and s3["verdict"]["verdict"] == dp.INCONCLUSIVE, f"abort {s3.get('status')}")
    # the native-time cap marks the run PARTIAL (exit 0) and the verdict INCONCLUSIVE
    clock4 = Clock()
    fake4 = Fake(w, p, shift, clock=clock4, step_s=30.0)
    code4, s4, run4 = engine(w, S, fake4, band=band, clock=clock4, max_wall_s=300.0, run_name="run_cap")
    check(code4 == 0 and s4["status"] == "PARTIAL" and s4["verdict"]["verdict"] == dp.INCONCLUSIVE and 0 < len(read_jsonl(run4 / "results.jsonl")) < len(rows),
          f"cap {s4.get('status')} {s4.get('counters')}")
    # forced: every departure breaks later than B
    clock5 = Clock()
    fake5 = Fake(w, p, lambda d, v: max(B + 1, d + (B - D)) if v == dp.VARIANT_CLEAR or d == D else None, clock=clock5)
    code5, s5, _ = engine(w, S, fake5, band=band, clock=clock5, run_name="run_forced")
    check(code5 == 0 and s5["verdict"]["verdict"] == dp.FORCED_IN_PROBE, f"forced {s5['verdict']}")
    # the clear not replaying exactly is PROBE_INVALID before any candidate
    clock6 = Clock()
    fake6 = Fake(w, p, shift, clock=clock6, mismatch=["clear_r2"])
    code6, s6, run6 = engine(w, S, fake6, band=band, clock=clock6, run_name="run_invalid")
    check(code6 == 3 and s6["status"] == "PROBE_INVALID" and not read_jsonl(run6 / "results.jsonl"), f"invalid {s6.get('status')}")
    # refusals: an existing run folder, readiness
    clock7 = Clock()
    code7, _, _ = engine(w, S, Fake(w, p, shift, clock=clock7), band=band, clock=clock7, run_name="run")
    check(code7 == 2, "an existing run folder is refused")
    clock8 = Clock()
    fake8 = Fake(w, p, shift, clock=clock8)
    code8, _, _ = engine(w, S, fake8, band=band, clock=clock8, ready=False, run_name="run_ready")
    check(code8 == 2 and not fake8.calls, "a readiness refusal launches nothing")
    return {"rows": len(rows), "verdict": v["verdict"], "not_dispatched": len(nd), "cap_rows": len(read_jsonl(run4 / "results.jsonl"))}


def report_ok(rep: str) -> bool:
    return rep.startswith("# Departure probe run (") and "**Verdict " in rep and "Did not depart at d:" in rep


@synthetic
def engine_stops_and_pre_break_gain() -> Dict[str, Any]:
    """The in-run control failing to reproduce B (PROBE_INVALID), a tick-contract failure (PROBE_INVALID on the first one), more than 10 %
    failures (PROBE_INCOMPLETE, verdict INCONCLUSIVE), and a pre-break departure reaching the baseline's progress before B (counted, labelled)."""
    w = World()
    S = thin(synthetic_plan(w), 8)
    p = S["P"]["plan"]
    D, B = p["departure"]["D"], p["baseline"]["B"]
    band = band_around(S)
    cands = S["P"]["candidates"]
    on_line, on_target = p["on_group_breaks"][0]
    late = lambda d, v: B + 1 if v == dp.VARIANT_CLEAR else None  # noqa: E731
    # the control breaks after B: PROBE_INVALID at the first candidate
    c1 = Clock()
    f1 = Fake(w, p, late, clock=c1, bad_control=True)
    code1, s1, _ = engine(w, S, f1, band=band, clock=c1, run_name="run_ctl")
    check(code1 == 3 and s1["status"] == "PROBE_INVALID" and "in-run control" in s1["stop"]["reason"] and s1["verdict"]["verdict"] == dp.INCONCLUSIVE,
          f"the in-run control {s1.get('status')} {s1.get('stop')}")
    # one tick-contract failure ends the run
    c2 = Clock()
    bad = cands[5]["label"]
    f2 = Fake(w, p, late, clock=c2, contract=[bad])
    code2, s2, run2 = engine(w, S, f2, band=band, clock=c2, run_name="run_contract")
    rows2 = read_jsonl(run2 / "results.jsonl")
    check(code2 == 3 and s2["status"] == "PROBE_INVALID" and "tick contract" in s2["stop"]["reason"] and s2["counters"]["contract"] == 1
          and [r["label"] for r in rows2 if r["outcome"] == "contract"] == [bad] and len(rows2) < len(cands) and s2["verdict"]["verdict"] == dp.INCONCLUSIVE,
          f"S6: a contract failure is PROBE_INVALID on the first occurrence {s2.get('status')} {s2.get('counters')}")
    # more than 10 % of the candidates fail to run
    c3 = Clock()
    errs = [c["label"] for c in cands[1:] if c["variant"] != dp.VARIANT_CLEAR][:int(0.1 * len(cands)) + 2]
    f3 = Fake(w, p, late, clock=c3, errors=errs)
    code3, s3, _ = engine(w, S, f3, band=band, clock=c3, run_name="run_failed")
    check(code3 == 4 and s3["status"] == "PROBE_INCOMPLETE" and s3["verdict"]["verdict"] == dp.INCONCLUSIVE
          and any("failed to run" in x for x in s3["verdict"]["reasons"]), f"more than 10 % failures {s3.get('status')} {s3['verdict']['reasons']}")
    # a pre-break departure that also breaks the on-group target reaches the baseline's progress before B: counted, labelled pre-break
    c4 = Clock()
    f4 = Fake(w, p, lambda d, v: (d + (B - D), [on_target, int(p["baseline"]["target"])]) if (v == dp.VARIANT_CLEAR and d < on_line)
              else (B + 1 if v == dp.VARIANT_CLEAR else None), clock=c4)
    code4, s4, run4 = engine(w, S, f4, band=band, clock=c4, run_name="run_pre")
    rows4 = read_jsonl(run4 / "results.jsonl")
    v4 = s4["verdict"]
    check(code4 == 0 and v4["verdict"] == dp.NOT_FORCED and v4["best"]["pre_break"] is True and v4["beats_B"] == v4["beats_B_pre_break"] > 0
          and v4["pre_break"]["counted_as_gain"] == v4["beats_B_pre_break"] and all(r["pre_break"] for r in rows4 if r.get("beats_B")),
          f"D2: a pre-break gain is counted {v4.get('verdict')} {v4.get('best')}")
    csv4 = (run4 / "curve.csv").read_text(encoding="utf-8").splitlines()
    hdr = csv4[0].split(",")
    pre_beats = [ln for ln in csv4[1:] if ln.split(",")[hdr.index("part")] == "pre_break" and ln.split(",")[hdr.index("beats_B")] == "True"]
    rep4 = (run4 / "report.md").read_text(encoding="utf-8")
    check(pre_beats and f"beat B {v4['beats_B_pre_break']} (counted, labelled pre-break)" in rep4 and "| True |" in rep4.split("Pre-break departures (")[1],
          "the pre-break gain is labelled in the curve and the report")
    return {"contract_rows": len(rows2), "pre_break_gains": v4["beats_B_pre_break"]}


@synthetic
def engine_pin_drift() -> Dict[str, Any]:
    """A pin drift (the pinned game files changed during the run, seen by rl/frs_verify's check before every replay) ends the run as
    PROBE_INVALID on the first detection, as a tick-contract failure does (S6): recorded in summary.json and report.md, no verdict drawn.
    Once the files have changed every later replay sees it; in a control it stops the run at open, before any candidate."""
    w = World()
    S = thin(synthetic_plan(w), 8)
    p = S["P"]["plan"]
    D, B = p["departure"]["D"], p["baseline"]["B"]
    band = band_around(S)
    cands = S["P"]["candidates"]
    shift = lambda d, v: (d + (B - D)) if v == dp.VARIANT_CLEAR else None  # noqa: E731
    # the pins change after the three controls and six candidates
    c1 = Clock()
    f1 = Fake(w, p, shift, clock=c1, drift_from=3 + 6)
    code1, s1, run1 = engine(w, S, f1, band=band, clock=c1, run_name="run_drift")
    rows1 = read_jsonl(run1 / "results.jsonl")
    drift = [r for r in rows1 if r["outcome"] == "pin_drift"]
    check(code1 == 3 and s1["status"] == "PROBE_INVALID" and drift and "pin drift" in s1["stop"]["reason"]
          and f"detected before {drift[0]['label']}" in s1["stop"]["reason"], f"a pin drift is PROBE_INVALID on the first detection {s1.get('stop')}")
    check(1 <= len(drift) <= 3 and s1["counters"]["pin_drift"] == len(drift) and sum(1 for r in rows1 if r.get("valid")) == 6
          and len(rows1) == 6 + len(drift) < len(cands) and len(f1.calls) == 3 + len(rows1),
          f"dispatching stops at the first detection; only the in-flight candidates finish {len(rows1)} {s1['counters']}")
    check(all(not r["valid"] and r["failed"] and r["pin_drift"]["detail"]["problems"] for r in drift), "a pin-drift row is not valid and carries the detail")
    check(s1["verdict"]["verdict"] == dp.INCONCLUSIVE and any("PROBE_INVALID" in x for x in s1["verdict"]["reasons"]), f"no verdict drawn {s1['verdict']['reasons']}")
    check([x["label"] for x in s1["integrity"]["pin_drift"]] == [r["label"] for r in drift] and s1["integrity"]["pin_drift"][0]["detail"]["problems"],
          f"summary.json records every detection {s1['integrity'].get('pin_drift')}")
    rep1 = (run1 / "report.md").read_text(encoding="utf-8")
    check(report_ok(rep1) and "Status **PROBE_INVALID** (the pinned game files changed during the run (pin drift" in rep1
          and f"/ {s1['counters']['contract']} / {len(drift)} |" in rep1 and '"pin_drift":[{"label":"' + drift[0]["label"] in rep1,
          "report.md records the pin drift: status, stop reason, counter and integrity")
    # the pins change before the controls: PROBE_INVALID at open (not PROBE_INCOMPLETE), no candidate dispatched
    c2 = Clock()
    f2 = Fake(w, p, shift, clock=c2, drift_from=0)
    code2, s2, run2 = engine(w, S, f2, band=band, clock=c2, run_name="run_drift_controls")
    ctl = json.loads((run2 / "controls.json").read_text(encoding="utf-8"))
    check(code2 == 3 and s2["status"] == "PROBE_INVALID" and "pin drift" in s2["stop"]["reason"] and s2["counters"]["pin_drift"] == 3
          and not read_jsonl(run2 / "results.jsonl") and sorted(f2.calls) == ["control_clear_r1", "control_clear_r2", "control_filler"]
          and sorted(x["label"] for x in ctl["pin_drift"]) == sorted(f2.calls) and s2["verdict"]["verdict"] == dp.INCONCLUSIVE
          and "pin drift" in (run2 / "report.md").read_text(encoding="utf-8"), f"a pin drift in a control {s2.get('status')} {s2.get('stop')}")
    return {"drift_rows": len(drift), "rows": len(rows1), "control_drift": s2["counters"]["pin_drift"]}


@synthetic
def run_guards_refuse() -> Dict[str, Any]:
    """S5 and N5 as functions: the output folder rule and the git rule."""
    lab = tmpdir("guards")
    (lab / "import").mkdir()
    out = lab / "departure_probe_x"
    check(dp.out_problems(out, lab, "a" * 64, "b" * 64) == [], "a new output folder is accepted")
    check(dp.out_problems(lab / "import", lab, "a" * 64, None) and dp.out_problems(lab / "import" / "x", lab, "a" * 64, None), "S5: import/ is refused")
    out.mkdir()
    (out / "plan.json").write_text(json.dumps({"candidate_set_digest": "a" * 64, "band": {"digest": "b" * 64}}), encoding="utf-8")
    (out / "candidates.jsonl").write_text("{}\n", encoding="utf-8")
    (out / "refused_20261103T000000Z.json").write_text("{}", encoding="utf-8")
    check(dp.out_problems(out, lab, "a" * 64, "b" * 64) == [], "a refused attempt's plan.json, candidates.jsonl and refused_*.json are accepted")
    check(any("another candidate set" in x for x in dp.out_problems(out, lab, "c" * 64, "b" * 64)), "another plan's plan.json is refused")
    check(any("another band" in x for x in dp.out_problems(out, lab, "a" * 64, "c" * 64)), "another band's plan.json is refused")
    (out / "run").mkdir()
    check(any(str(out / "run") in x for x in dp.out_problems(out, lab, "a" * 64, "b" * 64)), "an existing run folder is refused")
    (out / "run").rmdir()
    (out / "notes.txt").write_text("x", encoding="utf-8")
    check(any("notes.txt" in x for x in dp.out_problems(out, lab, "a" * 64, "b" * 64)), "any other file is refused")
    clean = {"head": "1" * 40, "tracked_changes": []}
    check(dp.tree_problems(clean, "1" * 40) == [], "a clean tree at the expected HEAD is accepted")
    check(any("differs from --expect-head" in x for x in dp.tree_problems(clean, "2" * 40)), "N5: a wrong HEAD is refused")
    check(any("differs from --expect-head" in x for x in dp.tree_problems(clean, "1" * 12)), "N5: the full hash is required")
    check(any("tracked changes" in x for x in dp.tree_problems({"head": "1" * 40, "tracked_changes": [" M tools/frs/x.py"]}, "1" * 40)),
          "N5: a dirty tree is refused")
    check(len(dp.tree_problems({"head": None, "tracked_changes": None}, "1" * 40)) == 2, "unreadable git state is refused")
    f = dp.git_facts()
    check(isinstance(f.get("head"), str) and len(f["head"]) == 40 and isinstance(f.get("tracked_changes"), list), f"git_facts reads this checkout {f}")
    return {"checks": 14}


# == command line (child processes: main() arms the lab guard) ==============================================================================


def cli(args: Sequence[str], timeout: float = 600.0) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(HERE / "departure_probe.py"), *args], capture_output=True, text=True, timeout=timeout, cwd=str(REPO))


def child(lab: Path, body: str, timeout: float = 600.0) -> subprocess.CompletedProcess:
    """dp.main in a child process with the stub analyser (and whatever `body` patches); `body` ends by calling sys.exit(dp.main([...]))."""
    code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import departure_probe as dp, departure_probe_tests as T; "
            "dp.load_clear.__defaults__ = ('best', T.stub_analyse); lab = %r\n" % (str(RL), str(HERE), str(lab))) + body
    return subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=timeout, cwd=str(REPO))


DIGESTS = ("P = dp.build_plan(dp.load_clear(dp.Path(lab), 'best', T.stub_analyse), dp.ProbeParams(), T.CLF)\n"
           "band = dp.band_of(dp.Path(lab), P['plan'], P['geo'], T.stub_analyse)\n"
           "dg, bd = P['plan']['candidate_set_digest'], band['digest']\n")
CLEAN = "dp.git_facts = lambda: {'head': 'f' * 40, 'tracked_changes': []}\n"


@synthetic
def command_line_refusals() -> Dict[str, Any]:
    lab = tmpdir("cli")
    flags = ["--expect-digest", "0" * 64, "--expect-band", "0" * 64, "--expect-head", "0" * 40]
    r = cli(["--dry-run", "--lab-root", str(lab), "--max-wall-min", "46"])
    check(r.returncode == 2 and "max-wall-min" in r.stdout, "N6: a cap above 45 minutes is refused with exit 2")
    r = cli(["--dry-run", "--lab-root", str(lab), "--slots", "6"])
    check(r.returncode == 2 and "slots" in r.stdout, "N6: more than 5 slots is refused with exit 2")
    r = cli(["run", "--dry-run", "--lab-root", str(lab)])
    check(r.returncode == 2 and "exactly one" in r.stdout, "run and --dry-run together are refused")
    for opt in ("--stride=2", "--half=flight"):
        r = cli(["--dry-run", "--lab-root", str(lab), opt])
        check(r.returncode == 2 and f"unrecognized arguments: {opt}" in r.stderr, f"N9: {opt} is not an option: {r.stderr[-200:]}")
    r = cli(["--dry-run", "--lab-root", str(lab), "--out", str(tmpdir("elsewhere"))])
    check(r.returncode == 2 and "not inside the lab root" in r.stdout, "an output folder outside the lab root is refused")
    r = cli(["--dry-run", "--lab-root", str(lab), "--out", str(lab / "runs" / "x")])
    check(r.returncode == 2 and "runs" in r.stdout, "an output folder under runs/ is refused")
    r = cli(["run", "--lab-root", str(lab), "--out", str(lab / "import" / "probe"), *flags])
    check(r.returncode == 2 and "import folder" in r.stdout and not (lab / "import").exists(), "S5: an output folder under import/ is refused")
    r = cli(["run", "--lab-root", str(lab), *flags])
    check(r.returncode == 2 and "no lab import" in r.stdout, "run without a lab import is refused")
    (lab / "import").mkdir()
    (lab / "import" / "import_manifest.json").write_text("{}", encoding="utf-8")
    r = cli(["run", "--lab-root", str(lab)])
    check(r.returncode == 2 and "--expect-digest, --expect-band, --expect-head" in r.stdout and not (lab / "lab.lock").exists(),
          f"run without the expected digests and HEAD: {r.stdout[-300:]}")
    # a lock held by a live process (this one) is refused and left in place
    (lab / "lab.lock").write_text(json.dumps({"pid": os.getpid(), "utc": "x", "what": "test"}) + "\n", encoding="utf-8")
    r = cli(["run", "--lab-root", str(lab), *flags])
    check(r.returncode == 2 and "another lab workload holds" in r.stdout and json.loads((lab / "lab.lock").read_text(encoding="utf-8"))["pid"] == os.getpid(),
          f"a lock held by a live process: {r.stdout[-300:]}")
    (lab / "lab.lock").unlink()
    synthetic_lab(World(), lab)
    # N5: the real checkout at a HEAD other than --expect-head
    r = child(lab, "sys.exit(dp.main(['run', '--lab-root', lab] + %r))" % flags)
    check(r.returncode == 2 and "differs from --expect-head" in r.stdout and not (lab / "lab.lock").exists() and not list(lab.glob("departure_probe_*")),
          f"a wrong HEAD is refused: {r.stdout[-300:]}")
    r = child(lab, "dp.git_facts = lambda: {'head': 'f' * 40, 'tracked_changes': [' M rl/frs_lab.py']}\n"
                   "sys.exit(dp.main(['run', '--lab-root', lab, '--expect-digest', '0' * 64, '--expect-band', '0' * 64, '--expect-head', 'f' * 40]))")
    check(r.returncode == 2 and "tracked changes" in r.stdout and not list(lab.glob("departure_probe_*")), f"a dirty tree is refused: {r.stdout[-300:]}")
    r = child(lab, CLEAN + "sys.exit(dp.main(['run', '--lab-root', lab, '--expect-digest', '0' * 64, '--expect-band', '0' * 64, '--expect-head', 'f' * 40]))")
    check(r.returncode == 2 and "differs from --expect-digest" in r.stdout and not (lab / "lab.lock").exists() and not list(lab.glob("departure_probe_*")),
          f"a different candidate set is refused before anything is written: {r.stdout[-300:]}")
    r = child(lab, CLEAN + DIGESTS + "sys.exit(dp.main(['run', '--lab-root', lab, '--expect-digest', dg, '--expect-band', '0' * 64, '--expect-head', 'f' * 40]))")
    check(r.returncode == 2 and "differs from --expect-band" in r.stdout and not list(lab.glob("departure_probe_*")), f"N3: a different band: {r.stdout[-300:]}")
    out = lab / "departure_probe_t"
    out.mkdir()
    (out / "stray.txt").write_text("x", encoding="utf-8")
    r = child(lab, CLEAN + DIGESTS + "sys.exit(dp.main(['run', '--lab-root', lab, '--out', lab + '/departure_probe_t', '--expect-digest', dg, "
                                     "'--expect-band', bd, '--expect-head', 'f' * 40]))")
    check(r.returncode == 2 and "output folder" in r.stdout and "stray.txt" in r.stdout and sorted(x.name for x in out.iterdir()) == ["stray.txt"]
          and not (lab / "lab.lock").exists(), f"S5: an existing output folder with other files is refused: {r.stdout[-300:]}")
    # N3: the dry run prints the band digest only with --band, and the phase 2 command carries it
    r = child(lab, "sys.exit(dp.main(['--dry-run', '--lab-root', lab]))")
    check(r.returncode == 0 and "band digest: not computed" in r.stdout and "--expect-band <run the dry run with --band>" in r.stdout,
          f"the dry run without --band: {r.stdout[-400:]} {r.stderr[-400:]}")
    r = child(lab, DIGESTS + "print('BAND', bd)\nsys.exit(dp.main(['--dry-run', '--band', '--lab-root', lab]))")
    bd = next(ln.split()[1] for ln in r.stdout.splitlines() if ln.startswith("BAND "))
    check(r.returncode == 0 and f"band digest {bd}" in r.stdout and f"--expect-band {bd} " in r.stdout, f"the dry run with --band: {r.stdout[-400:]}")
    return {"refusals": 16}


# == real-record tests (read-only) ===========================================================================================================


def real_plan() -> Dict[str, Any]:
    if not _REAL:
        clear = dp.load_clear(LAB, "best")
        P = dp.build_plan(clear, dp.ProbeParams(), CLF)
        _REAL.update({"clear": clear, "P": P})
    return _REAL


@real
def real_clear_records_are_consistent() -> Dict[str, Any]:
    R = real_plan()
    clear = R["clear"]
    ident = clear["ident"]
    check(ident["is_best_verified"], "the probed clear is the fastest VERIFIED lab clear")
    check(clear["breaks"] == fv.breaks_of(clear["r1"], fv.real_analyse) == fv.breaks_of(clear["r2"], fv.real_analyse) == clear["row"]["breaks_r1"],
          "the native-record break table equals the target diagnostic's, in both traces")
    check(clear["chain"][-1].hex() == ident["final_chain"] and dp.chain_list(clear["r2"]) == clear["chain"], "r1 and r2 chains equal per tick")
    check(not clear["break_anomalies"] and not dp.required_field_problems(clear["r1"]), "no anomaly, no missing field")
    return {k: ident[k] for k in ("run", "n", "cid", "completion_input_tick", "words")}


@real
def real_geometry_is_read_from_the_record() -> Dict[str, Any]:
    R = real_plan()
    p, tr = R["P"]["plan"], R["clear"]["r1"]
    lines = dp.line_groups(tr)
    check(all(lines[ln] == p["group"] for ln in p["group_lines"]) and p["group_lines"], "the group's lines come from the line table")
    dep = p["departure"]
    check(all(dp.floor_line(dp.reply_at(tr, t)) in p["group_lines"] for t in range(dep["C0"], dep["C1"] + 1)), "every contact tick is on the group")
    check(dp.floor_line(dp.reply_at(tr, dep["C1"] + 1)) not in p["group_lines"] and dp.floor_line(dp.reply_at(tr, dep["C0"] - 1)) not in p["group_lines"],
          "the interval is maximal")
    st = lambda t: dp.reply_at(tr, t)["observation"]["fighter_status_id"]  # noqa: E731
    check(dep["C0"] <= dep["D"] < dep["S"] <= dep["G"] < dep["A"] <= dep["C1"] and dep["grounded_D"], "C0 <= D < S <= G < A <= C1")
    check(all(st(t) == st(dep["G"]) for t in range(dep["S"], dep["G"] + 1)) and st(dep["D"]) != st(dep["S"]), "the exit's status run")
    check(not dp.grounded(dp.reply_at(tr, dep["A"])) and all(not dp.grounded(dp.reply_at(tr, t)) for t in range(dep["A"], dep["C1"] + 1)),
          "the exit is airborne to the interval's end")
    md = dp.measured_departure(tr, dep["D"], set(p["group_lines"]))
    check(md["departure_tick"] == dep["D"] and md["reason"] == "at_d" and md["floor_line_leave_tick"] == dep["L"],
          f"S2: the candidate rule measures the clear's own departure at D {md}")
    per = p["period"]
    check(all(x == per["P"] for x in per["gaps"]["bottom"] + per["gaps"]["top"]), f"every gap equals P {per}")
    base = p["baseline"]
    check(base["B"] > dep["D"] and [base["B"], base["target"]] in R["clear"]["breaks"]
          and not any(dep["D"] < t < base["B"] for t, _i in R["clear"]["breaks"]), "B is the first break after D")
    check(base["mask_before"] >> base["target"] & 1 and not base["mask"] >> base["target"] & 1, "the target's bit is cleared at B")
    F = next(t for t in range(dep["C0"], dep["C1"] + 1) if dp.grounded(dp.reply_at(tr, t)))
    w = p["window"]
    check(dep["F"] == F and w["earlier"] == [F, dep["D"], dep["D"] - F + 1] and w["later"] == [dep["D"] + 1, dep["D"] + per["P"], per["P"]], "window")
    onb = [b for b in R["clear"]["breaks"] if dep["F"] <= b[0] <= dep["D"]]
    check(p["on_group_breaks"] == onb, "N1: the on-group breaks are the clear's breaks from F to D")
    for c in R["P"]["candidates"]:
        check(c["pre_break"] == any(c["d"] < t for t, _i in onb), f"{c['label']}: pre-break")
    xr, sp = p["exit_run"], p["spans"]
    check(xr["all_airborne"] and xr["floor_lines"] == p["group_lines"] and xr["at_L"]["floor_line_id"] not in p["group_lines"], "the exit run")
    lo, hi = xr["at_C1"]["group_line_span"]
    xl = xr["at_L"]["x" if xr["position_axis"] == "position_x" else "y"]
    xc = xr["at_C1"]["x" if xr["position_axis"] == "position_x" else "y"]
    check(lo <= xc <= hi and not lo <= xl <= hi, "C1 is the last tick inside the line's extent; L is outside it")
    land = next(t for t in range(dep["L"], base["B"] + 1) if dp.grounded(dp.reply_at(tr, t)))
    check(sp["landing"] == land and sp["parts_sum"] == base["B_minus_D"] and sp["B_minus_L"] == base["B"] - dep["L"], f"spans {sp}")
    return {"group": p["group"], "lines": p["group_lines"], "C0": dep["C0"], "F": F, "D": dep["D"], "B": base["B"], "P": per["P"],
            "pre_break": p["pre_break"]["d"], "spans": sp["parts"], "candidates": p["candidates"]}


@real
def real_plan_is_deterministic_and_follows_the_method() -> Dict[str, Any]:
    R = real_plan()
    p, cands, words = R["P"]["plan"], R["P"]["candidates"], R["clear"]["words"]
    again = dp.build_plan(dp.load_clear(LAB, "best"), dp.ProbeParams(), CLF)
    check(again["plan"]["candidate_set_digest"] == p["candidate_set_digest"], "the candidate set is deterministic")
    D, B, E = p["departure"]["D"], p["baseline"]["B"], p["budget"]["E"]
    for c in cands:
        d = c["d"]
        prefix = words[:d] if d <= D else words[:D] + bytes([dp.NEUTRAL_WORD]) * (d - D)
        check(c["words"][:d] == prefix and len(c["words"]) == d + E, f"{c['label']}")
    check(cands[0]["side"] == "control" and cands[0]["words"][:B] == words[:B], "the control")
    return {"candidates": len(cands), "digest": p["candidate_set_digest"][:16]}


@real
def real_dry_run_writes_nothing() -> Dict[str, Any]:
    def listing() -> Dict[str, float]:
        return {str(p): p.stat().st_mtime for p in sorted(LAB.glob("*")) + sorted(LAB.glob("*/*")) + sorted(LAB.glob("crossing_2026-10-15_run2/run/*"))}

    before = listing()
    r = cli(["--dry-run", "--lab-root", str(LAB)])
    check(r.returncode == 0, f"dry run exit {r.returncode}: {r.stderr[-1500:]}")
    for needle in ("moving group:", "contact interval 0 (chosen)", "departure:", "period: P", "baseline: B", "window (full", "candidates:",
                   "exit run A", "spans: D", "pre-break departures d", "window start:", "progress: a candidate beats B", "band digest: not computed",
                   "git: HEAD", "output folder", "zero native ticks, nothing written", "phase 2 command:",
                   "--expect-digest " + real_plan()["P"]["plan"]["candidate_set_digest"], "--expect-band ", "--expect-head "):
        check(needle in r.stdout, f"the dry run prints {needle!r}")
    check(listing() == before and not (LAB / "lab.lock").exists(), "the dry run wrote nothing in the lab root and took no lock")
    return {"lines": r.stdout.count("\n")}


@real
def real_source_has_no_record_literal() -> Dict[str, Any]:
    """No numeric literal in the probe's source equals a tick, period, line id, coordinate or budget read from the record (values >= 10)."""
    R = real_plan()
    p = R["P"]["plan"]
    dep, base, per = p["departure"], p["baseline"], p["period"]
    derived = {dep[k] for k in ("C0", "C1", "G", "A", "S", "D")} | {base["B"], base["B_minus_D"], p["budget"]["E"], per["P"], per["origin"],
                                                                   dep["D"] + per["P"], p["clear"]["completion_input_tick"], p["clear"]["completion_time_passed"]}
    derived |= set(p["group_lines"]) | {p["group"], base["target"], dep["F"], dep["L"]}
    sp = p["spans"]
    derived |= {sp["landing"], sp["B_minus_L"], *sp["parts"].values(), *[t for t, _i in p["on_group_breaks"]], *p["pre_break"]["d"]}
    derived |= set(p["exit_run"]["at_C1"]["group_line_span"] or [])
    for gm in p["groups"]:
        for lo, hi in gm["ranges"]:
            derived |= {lo, hi}
    derived = {float(x) for x in derived if abs(float(x)) >= 10}
    src = (HERE / "departure_probe.py").read_text(encoding="utf-8")
    lits = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.NUMBER:
            try:
                lits.add(float(eval(tok.string)))  # noqa: S307 - a numeric literal token
            except (ValueError, SyntaxError):
                pass
    hits = sorted(lits & derived)
    check(not hits, f"record values written as literals in the probe: {hits}")
    return {"derived_values": len(derived), "literals": len(lits)}


# =============================================================================================================================================


def main(argv: Sequence[str]) -> int:
    global LAB
    args = list(argv[1:])
    if "--lab-root" in args:
        i = args.index("--lab-root")
        LAB = Path(args[i + 1])
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
            extra = json.dumps(info, default=str, separators=(",", ":"))[:400] if info else ""
            print(f"PASS {name} ({time.perf_counter() - t0:.1f} s) {extra}", flush=True)
        except Exception as exc:  # noqa: BLE001 - reported per test
            print(f"FAIL {name} ({time.perf_counter() - t0:.1f} s): {type(exc).__name__}: {exc}"[:3000], flush=True)
            print(traceback.format_exc()[-2500:], flush=True)
    for p in CREATED:
        shutil.rmtree(p, ignore_errors=True)
    print(f"departure probe tests: {passed}/{len(pick)} passed in {time.perf_counter() - t_all:.0f} s")
    return 0 if passed == len(pick) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
