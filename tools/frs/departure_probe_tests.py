#!/usr/bin/env python3
"""Zero-tick tests of the departure probe (tools/frs/departure_probe.py). No game process is started: synthetic traces (arbitrary group and
line ids, period, ticks and targets) stand in for the game in the derivation, candidate, verdict and engine checks; the real lab records of
the probed clear are read (never written) for the record checks; the command-line refusals run in child processes (the lab guard is an
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
                                                     (600, 1)), lo: float = 1000.0, hi: float = 2000.0, moving: bool = True, hover: Tuple[int, int] = (113, 118)):
        self.n, self.gid, self.glines, self.static_lines, self.P, self.bottom = n, gid, list(glines), list(static_lines), P, bottom
        self.intervals, self.squat, self.breaks, self.lo, self.hi, self.moving, self.hover = list(intervals), squat, list(breaks), lo, hi, moving, hover
        self.words = bytes((i * 7 + 3) % mcell.TRACK1_WORDS for i in range(n))

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


def synthetic_lab(world: World, root: Optional[Path] = None) -> Tuple[Path, Dict[str, Any]]:
    """A temporary lab root holding one verification row and its two traces (r2 = r1, as a verified clear's)."""
    lab = root or tmpdir("lab")
    tr = world.base_trace()
    ev = fv.evaluate(tr, world.words, stub_analyse)
    check(ev["outcome"] == "clear", f"the synthetic base trace clears: {ev['outcome']}")
    run = lab / "synthrun" / "run"
    row = {"mode": "lab", "kind": "clear", "n": 1, "cid": 2, "k": 0, "words": len(world.words), "words_hex": world.words.hex(),
           "words_digest": mcell.words_digest(world.words), "verdict": fv.VERIFIED, "completion_input_tick": ev["completion_input_tick"],
           "completion_time_passed": ev["completion_time_passed"], "chain_r1": ev["final_chain"], "chain_r2": ev["final_chain"], "breaks_r1": ev["breaks"],
           "breaks_r2": ev["breaks"], "claim": {"words_digest": mcell.words_digest(world.words), "completion_input_tick": ev["completion_input_tick"],
                                                "completion_time_passed": ev["completion_time_passed"], "chain": ev["final_chain"]}}
    run.mkdir(parents=True, exist_ok=True)
    (run / "verifications.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    write_gz(run / "traces" / "clear_n1_c2_k0_r1.json.gz", tr)
    write_gz(run / "traces" / "clear_n1_c2_k0_r2.json.gz", tr)
    return lab, {"row": row, "trace": tr}


def synthetic_plan(world: World, params: Optional[dp.ProbeParams] = None) -> Dict[str, Any]:
    lab, info = synthetic_lab(world)
    clear = dp.load_clear(lab, "best", stub_analyse)
    P = dp.build_plan(clear, params or dp.ProbeParams(), CLF)
    return {"lab": lab, "clear": clear, "P": P, **info}


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
    win = p["window"]
    check(win["earlier"] == [gs, dep["D"], dep["D"] - gs + 1] and win["later"] == [dep["D"] + 1, dep["D"] + w.P, w.P], f"window {win}")
    check(win["excluded_airborne_contact"] == [s, gs - 1, gs - s], "the airborne contact ticks before the first grounded tick are excluded")
    check(p["candidates"] == (dep["D"] - gs + 1 + w.P) * 2 and p["variants"]["K"] == 1, f"candidates {p['candidates']}")
    onb = [[t, i] for t, i in w.breaks if s <= t <= dep["D"]]
    check(p["on_group_breaks"] == onb and len(onb) == 1, f"on-group breaks from the record {p['on_group_breaks']}")
    check(p["pre_break"]["d"] == [gs, onb[0][0] - 1, onb[0][0] - gs], f"pre-break departures {p['pre_break']}")
    for c in S["P"]["candidates"]:
        check(c["pre_break"] == (c["d"] < onb[0][0]) and (c["pending_on_group"] == onb) == c["pre_break"], f"{c['label']}: pre-break flag")
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
def window_reductions_and_order() -> Dict[str, Any]:
    w = World()
    S = synthetic_plan(w)
    geo, D = S["P"]["geo"], S["P"]["plan"]["departure"]["D"]
    full = dp.window_of(geo)
    s3 = dp.window_of(geo, stride=3)
    check(D in s3["earlier"] and min(s3["earlier"]) == geo["departure"]["F"] and all((d - geo["departure"]["F"]) % 3 == 0 or d == D for d in s3["earlier"])
          and all((d - D) % 3 == 0 for d in s3["later"]), "stride keeps D and every 3rd tick")
    hf = dp.window_of(geo, half="flight", trace=S["clear"]["r1"])
    sign = dp.flight_sign(S["clear"]["r1"], geo)
    check(sign == 1 and D in hf["earlier"] and all(d == D or dp.direction_at(geo["y"], d) == sign for d in hf["earlier"] + hf["later"]),
          "the half-cycle rule keeps the group's direction of the clear's next flight (and D)")
    check(len(hf["earlier"]) + len(hf["later"]) < len(full["earlier"]) + len(full["later"]), "the half-cycle rule reduces the window")
    for n in (1, 2, 7, 64, 300):
        o = dp.bit_reverse_order(n)
        check(sorted(o) == list(range(n)), f"the order is a permutation ({n})")
    o = dp.bit_reverse_order(64)
    check(set(o[:8]) == set(range(0, 64, 8)), "every prefix of the order spreads over the range")
    cands = S["P"]["candidates"]
    check(cands[0]["side"] == "control" and cands[0]["d"] == D and cands[0]["variant"] == dp.VARIANT_CLEAR, "the control is dispatched first")
    check(len({(c["d"], c["variant"]) for c in cands}) == len(cands), "each (d, variant) once")
    return {"full": len(full["earlier"]) + len(full["later"]), "stride3": len(s3["earlier"]) + len(s3["later"]),
            "half": len(hf["earlier"]) + len(hf["later"])}


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
    group), then a flight whose first break (the baseline's target, or none) is set by `break_at(d, variant)`."""

    def __init__(self, w: World, plan: Mapping[str, Any], break_at: Callable[[int, str], Optional[int]], *, filler_off: Optional[int] = None,
                 mismatch: Sequence[str] = (), clock: Optional["Clock"] = None, step_s: float = 1.0, fall: Sequence[str] = ()):
        self.w, self.plan, self.break_at, self.filler_off = w, plan, break_at, filler_off
        self.mismatch, self.clock, self.step_s, self.fall = set(mismatch), clock, step_s, set(fall)
        self.D, self.B = int(plan["departure"]["D"]), int(plan["baseline"]["B"])
        self.target = int(plan["baseline"]["target"])
        self.base = [w.base_reply(t) for t in range(0, w.n + 1)]
        self.calls: List[str] = []
        self._lock = threading.Lock()

    def filler_reply(self, t: int) -> Dict[str, Any]:
        on = self.filler_off is None or t < self.filler_off
        return self.w.reply(t, line=self.w.glines[0] if on else self.w.static_lines[0], ground=on, status=10, x=100.0 + self.D,
                            mask=self.w.mask_at(self.D), records=self.w.records_at(self.D))

    def replay(self, words: bytes, label: str, slot: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.calls.append(label)
        if self.clock is not None:
            self.clock.advance(self.step_s)
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
        if d == self.D and v == dp.VARIANT_CLEAR:
            return self.w.trace([self.base[t] for t in range(1, n + 1)], words, label)
        pre = [self.base[t] if t <= self.D else self.filler_reply(t) for t in range(1, d + 1)]
        if label in self.mismatch:
            pre[0] = copy.deepcopy(pre[0])
            pre[0]["observation"]["position_x"] += 0.25
        tb = self.break_at(d, v)
        targets = [self.target]
        if isinstance(tb, tuple):
            tb, targets = tb
        m0 = pre[-1]["spatial"]["target_live_mask"]
        rec0 = pre[-1]["targets"]["records"]
        post = []
        for t in range(d + 1, n + 1):
            m, rec = m0, rec0
            if tb is not None and t >= tb:
                for i in targets:
                    m &= ~(1 << i)
                rec = [dict(r, break_input_tick=tb) if int(r["id"]) in targets else r for r in rec0]
            fall = label in self.fall and t == n
            post.append(self.w.reply(t, line=self.w.static_lines[2], ground=False, status=22, x=50.0 - t, vy=-2.0, mask=m, records=rec,
                                     game_status=mcell.GAME_STATUS_END if fall else 1))
        return self.w.trace(pre + post, words, label)


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


@synthetic
def reading_a_candidate() -> Dict[str, Any]:
    w = World()
    S = synthetic_plan(w)
    p = S["P"]["plan"]
    D, B = p["departure"]["D"], p["baseline"]["B"]
    on_line = next(t for t, _i in w.breaks if w.intervals[1][0] <= t <= D)          # the break taken while riding the group
    plan_breaks = {(on_line + 5, "a"): B - 10, (D - 3, "a"): B - 7, (D + 4, "a"): B + 20}
    fake = Fake(w, p, lambda d, v: plan_breaks.get((d, v)), mismatch=(f"d{D - 2:05d}_a",), fall=(f"d{D - 1:05d}_g1",))
    ctx = ctx_of(S, fake)
    rd = lambda d, v: dp.read_candidate(fake.replay(cand_of(S, d, v)["words"], cand_of(S, d, v)["label"], 0), cand_of(S, d, v), ctx)  # noqa: E731
    ctl = rd(D, "a")
    check(ctl["valid"] and ctl["prefix_equal"] and ctl["chain_at_B_equal"] and ctl["first_break"]["tick"] == B and not ctl["beats_B"], f"control {ctl}")
    check(ctl["first_break"]["same_as_baseline_next"] and ctl["comparable"], "the control is the baseline's own next break")
    a = rd(on_line + 5, "a")
    check(a["valid"] and a["beats_B"] and a["gain"] == 10 and a["comparable"] and a["first_break"]["exit_ticks"] == B - 10 - (on_line + 5), f"beats {a}")
    check(a["end_state"]["grounded"] is False and "helpless" in a["end_state"] and a["end_state"]["status"] == 22, "the end state at the break")
    check(not a["pre_break"] and a["pending_on_group"] == [], "a departure after the on-group break is not pre-break")
    before = rd(on_line - 4, "a")
    check(before["valid"] and before["pre_break"] and before["first_break"] is None and not before["beats_B"], "no break within the budget")
    on_target = next(i for t, i in w.breaks if t == on_line)
    fake.break_at = lambda d, v: (B - 50 if d == on_line - 6 else (B - 30, [on_target, fake.target]) if d == on_line - 8
                                  else (B - 40, [on_target]) if d == on_line - 10 else plan_breaks.get((d, v)))
    less = rd(on_line - 6, "a")
    check(less["pre_break"] and less["earlier_than_B"] and not less["comparable"] and not less["beats_B"] and less["gain"] is None,
          f"an earlier break that leaves the on-group target live is less progress, never faster: {less}")
    both = rd(on_line - 8, "a")
    check(both["pre_break"] and both["earlier_than_B"] and both["comparable"] and not both["beats_B"] and both["gain"] is None
          and both["first_break"]["on_group_target"] and sorted(both["first_break"]["targets_at_tick"]) == sorted([on_target, fake.target]),
          f"a pre-break departure is never counted as a gain, even with the baseline's progress: {both}")
    ong = rd(on_line - 10, "a")
    check(ong["pre_break"] and ong["first_break"]["target"] == on_target and ong["first_break"]["on_group_target"]
          and not ong["first_break"]["same_as_baseline_next"], f"which break a pre-break departure reaches first: {ong['first_break']}")
    later = rd(D + 4, "a")
    check(later["valid"] and later["first_break"]["tick"] == B + 20 and not later["earlier_than_B"] and later["prefix_ref"] == "filler", f"later {later}")
    mm = rd(D - 2, "a")
    check(mm["outcome"] == "mismatch" and mm["failed"] and not mm["valid"] and mm["mismatch_first_tick"] == 1, f"a prefix mismatch {mm}")
    fl = rd(D - 1, "g1")
    check(fl["outcome"] == "fall" and fl["valid"], f"a fall is an outcome, not a failure {fl['outcome']}")
    tr = copy.deepcopy(fake.replay(cand_of(S, D - 3, "a")["words"], cand_of(S, D - 3, "a")["label"], 0))
    tr["steps"][20]["consumed_tick"] = 99
    bad = dp.read_candidate(tr, cand_of(S, D - 3, "a"), ctx)
    check(bad["outcome"] == "contract" and bad["failed"], "a tick-contract violation fails the candidate")
    tr2 = copy.deepcopy(fake.replay(cand_of(S, D - 3, "a")["words"], cand_of(S, D - 3, "a")["label"], 0))
    tr2["action_digest"] = "0" * 64
    check(dp.read_candidate(tr2, cand_of(S, D - 3, "a"), ctx)["outcome"] == "contract", "an action-digest mismatch fails the candidate")
    err = dp.read_candidate(None, cand_of(S, D - 3, "a"), ctx, ["boom"])
    check(err["outcome"] == "error" and err["failed"], "a replay that could not run")
    return {"B": B, "beat_gain": a["gain"]}


def mk_row(d: int, *, in_band: bool, tick: Optional[int], comparable: bool = True, B: int = 100, failed: bool = False, variant: str = "a",
           pre_break: bool = False, target: int = 3) -> Dict[str, Any]:
    r: Dict[str, Any] = {"d": d, "variant": variant, "side": "earlier", "in_band": in_band, "valid": not failed, "failed": failed, "d_phase": d % 50,
                         "pre_break": pre_break}
    if failed:
        r["outcome"] = "error"
        return r
    if tick is None:
        r.update(first_break=None, beats_B=False, earlier_than_B=False, comparable=None)
    else:
        counts = tick < B and comparable and not pre_break
        r.update(first_break={"tick": tick, "target": target, "on_group_target": pre_break and target != 3, "same_as_baseline_next": target == 3},
                 comparable=comparable, earlier_than_B=tick < B, beats_B=counts, gain=B - tick if counts else None, end_state={"grounded": False})
    return r


@synthetic
def verdict_rules() -> Dict[str, Any]:
    B = 100
    base = [mk_row(1, in_band=True, tick=B), mk_row(2, in_band=False, tick=None), mk_row(3, in_band=False, tick=B + 5)]
    v = dp.verdict_of(base + [mk_row(4, in_band=False, tick=B - 9), mk_row(5, in_band=False, tick=B - 3)], 5, "COMPLETED", B, True)
    check(v["verdict"] == dp.NOT_FORCED and v["best"]["gain"] == 9 and v["best"]["d"] == 4 and v["d_beating_B_outside_band"] == 2, f"not forced {v}")
    v = dp.verdict_of(base + [mk_row(4, in_band=False, tick=B - 9, comparable=False)], 4, "COMPLETED", B, True)
    check(v["verdict"] == dp.FORCED_IN_PROBE and v["earlier_with_less_progress"] == 1, f"forced (less progress is never faster) {v}")
    v = dp.verdict_of(base, 3, "COMPLETED", B, True)
    check(v["verdict"] == dp.FORCED_IN_PROBE and v["outside_band_no_break"] == 1 and v["outside_band_later_break"] == 1, f"forced {v}")
    v = dp.verdict_of(base + [mk_row(4, in_band=True, tick=B - 2)], 4, "COMPLETED", B, True)
    check(v["verdict"] == dp.IN_BAND_GAIN and v["best"]["in_band"] is True, f"in-band gain {v}")
    pre = [mk_row(40, in_band=False, tick=B - 20, pre_break=True), mk_row(41, in_band=False, tick=B - 25, pre_break=True, target=9),
           mk_row(42, in_band=True, tick=None, pre_break=True)]
    v = dp.verdict_of(base + pre, 6, "COMPLETED", B, True)
    pb = v["pre_break"]
    check(v["verdict"] == dp.FORCED_IN_PROBE and v["beats_B"] == 0 and pb["valid"] == 3 and pb["counted_as_gain"] == 0 and pb["earlier_than_B"] == 2
          and pb["first_break_by_target"]["9"]["on_group_target"] == 1 and pb["first_break_by_target"]["3"]["earliest_tick"] == B - 20
          and pb["first_break_by_target"]["none"]["candidates"] == 1, f"pre-break departures are reported apart, never gains {v}")
    v = dp.verdict_of([mk_row(1, in_band=True, tick=B)] + pre, 4, "COMPLETED", B, True)
    check(v["verdict"] == dp.INCONCLUSIVE and any("pre-break" in x for x in v["reasons"]), "pre-break departures do not stand for the outside of the band")
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
    check(v["verdict"] == dp.INCONCLUSIVE, "nothing tested outside the band")
    cbt = dp.curve_by_type(base + [mk_row(1, in_band=True, tick=B - 1, variant="g1"), mk_row(1, in_band=True, tick=None, variant="g2")] + pre)
    check(cbt["clear_exit"]["1"] == B and cbt["generic"]["1"] == B - 1 and cbt["clear_exit"]["2"] is None, f"curve by type {cbt}")
    check(cbt["pre_break_clear_exit"]["40"] == B - 20 and "40" not in cbt["clear_exit"], "the pre-break departures are their own part of the curve")
    csv = dp.curve_csv(base + pre)
    check(csv.count("\n") == 7 and csv.startswith("d,variant,") and csv.count(",pre_break,") == 3, "curve.csv labels the pre-break part")
    return {"rules": 11}


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


def engine(w: World, S: Mapping[str, Any], fake: Fake, *, band: Optional[Mapping[str, Any]], clock: Clock, max_wall_s: float = 2700.0,
           ready: bool = True, run_name: str = "run", save: bool = False) -> Tuple[int, Dict[str, Any], Path]:
    lab = S["lab"]
    out = lab / "departure_probe_test"
    run_dir = out / run_name
    env = fr.LabEnv(worker_spec=lambda rank: {}, replay=fake.replay, analyse=stub_analyse,
                    readiness=(lambda: {"ok": True, "problems": []}) if ready else (lambda: {"ok": False, "problems": ["test refusal"]}),
                    battleship_pids=lambda: [], snapshot=lambda: None, import_problems=lambda: [], wait_no_battleship=lambda t: [],
                    code_manifest=lambda: {}, backend="stub", now=clock.now, log=lambda s: None, sample_s=0.2, row_every_s=0.5)
    cfg = dp.ProbeConfig(lab_root=lab, out=out, run_dir=run_dir, slots=3, max_wall_s=max_wall_s, stop_reserve_s=0.0, progress_every_s=5.0, save_traces=save)
    code = dp.Probe(cfg, env, S["clear"], S["P"], band, CLF, {"available": False}).run()
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8")) if (run_dir / "summary.json").is_file() else {}
    return code, s, run_dir


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()] if p.is_file() else []


@synthetic
def engine_end_to_end() -> Dict[str, Any]:
    w = World()
    S = synthetic_plan(w, dp.ProbeParams(stride=8))
    p = S["P"]["plan"]
    D, B, Pp = p["departure"]["D"], p["baseline"]["B"], p["period"]["P"]
    phD = dp.phase_of(D, S["P"]["geo"]["period"])
    band = {"arc": {"start": (phD - 10) % Pp, "length": 20}, "P": Pp, "rule": "test", "sources": 1, "axis_value_range": None, "directions": [-1]}
    shift = lambda d, v: (d + (B - D)) if v == dp.VARIANT_CLEAR else None  # noqa: E731
    clock = Clock()
    earlier = [c["label"] for c in S["P"]["candidates"] if c["side"] == "earlier"]
    fake = Fake(w, p, shift, clock=clock, filler_off=D + 50, mismatch=earlier[2:4])
    code, s, run_dir = engine(w, S, fake, band=band, clock=clock, save=True)
    rows = read_jsonl(run_dir / "results.jsonl")
    nd = read_jsonl(run_dir / "not_dispatched.jsonl")
    check(code == 0 and s["status"] == "COMPLETED", f"status {s.get('status')} {s.get('stop')}")
    check(s["controls"]["clear"]["verdict"] == fv.VERIFIED and all(s["controls"]["clear"]["per_tick_chain_equal"].values()), "the clear replays twice exactly")
    check(s["later_max_d"] == D + 49 and nd and all(x["d"] > D + 49 for x in nd), f"the filler truncates the later window {s['later_max_d']}")
    lc = s["later_cut"]
    check(lc["filler_first_tick_off_group"] == D + 50 and lc["later_max_d"] == D + 49 and lc["cut"] and lc["later_dispatched_d"] < lc["later_planned_d"]
          and "complete" in lc["counted_as"], f"the measured cut point is reported and counted as complete {lc}")
    pbs = s["verdict"]["pre_break"]
    check(pbs["valid"] > 0 and pbs["counted_as_gain"] == 0 and s["verdict"]["beats_B"] == sum(1 for r in rows if r.get("beats_B"))
          and not any(r.get("beats_B") for r in rows if r.get("pre_break")), f"pre-break rows are never gains {pbs}")
    check("Pre-break departures" in (run_dir / "report.md").read_text(encoding="utf-8") and ",pre_break," in (run_dir / "curve.csv").read_text(encoding="utf-8"),
          "the report and the curve carry the pre-break part")
    check(len(rows) == p["candidates"] - len(nd) == s["planned_after_filler"], f"every dispatched candidate returned {len(rows)}")
    check(s["counters"]["mismatches"] == 2 and sum(1 for r in rows if r["outcome"] == "mismatch") == 2, "two mismatches retired, the run continued")
    v = s["verdict"]
    check(v["verdict"] == dp.NOT_FORCED and v["best"]["in_band"] is False and v["best"]["gain"] > 0, f"verdict {v}")
    ctl = next(r for r in rows if r["side"] == "control")
    check(ctl["first_break"]["tick"] == B and ctl["chain_at_B_equal"], "the in-run control reproduces B")
    for f in ("plan.json",):
        check(not (run_dir.parent / f).exists(), "the engine writes no plan (the command does)")
    for f in ("config.json", "controls.json", "results.jsonl", "summary.json", "report.md", "curve.csv", "run_log.jsonl"):
        check((run_dir / f).is_file(), f"{f} written")
    check((run_dir / "traces" / f"{ctl['label']}.json.gz").is_file() and (run_dir / "traces" / "control_filler.json.gz").is_file(), "traces saved")
    check((run_dir / "report.md").read_text(encoding="utf-8").startswith("# Departure probe run ("), "report.md")
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


# == command line (child processes: main() arms the lab guard) ==============================================================================


def cli(args: Sequence[str], timeout: float = 600.0) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", str(HERE / "departure_probe.py"), *args], capture_output=True, text=True, timeout=timeout, cwd=str(REPO))


@synthetic
def command_line_refusals() -> Dict[str, Any]:
    lab = tmpdir("cli")
    r = cli(["--dry-run", "--lab-root", str(lab), "--max-wall-min", "46"])
    check(r.returncode != 0 and "max-wall-min" in (r.stderr + r.stdout), "a cap above 45 minutes is refused")
    r = cli(["run", "--dry-run", "--lab-root", str(lab)])
    check(r.returncode != 0 and "exactly one" in (r.stderr + r.stdout), "run and --dry-run together are refused")
    r = cli(["--dry-run", "--lab-root", str(lab), "--out", str(tmpdir("elsewhere"))])
    check(r.returncode != 0 and "not inside the lab root" in (r.stderr + r.stdout), "an output folder outside the lab root is refused")
    r = cli(["--dry-run", "--lab-root", str(lab), "--out", str(lab / "runs" / "x")])
    check(r.returncode != 0 and "runs" in (r.stderr + r.stdout), "an output folder under runs/ is refused")
    r = cli(["run", "--lab-root", str(lab)])
    check(r.returncode != 0 and "no lab import" in (r.stderr + r.stdout), "run without a lab import is refused")
    (lab / "import").mkdir()
    (lab / "import" / "import_manifest.json").write_text("{}", encoding="utf-8")
    r = cli(["run", "--lab-root", str(lab)])
    check(r.returncode == 2 and "expect-digest" in r.stdout and not (lab / "lab.lock").exists(), f"run without --expect-digest: {r.stdout[-300:]}")
    synthetic_lab(World(), lab)
    code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import departure_probe as dp, departure_probe_tests as T; "
            "dp.load_clear.__defaults__ = ('best', T.stub_analyse); sys.exit(dp.main(['run', '--lab-root', %r, '--expect-digest', '0' * 64]))"
            % (str(RL), str(HERE), str(lab)))
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=600, cwd=str(REPO))
    check(r.returncode == 2 and "differs from --expect-digest" in r.stdout and not (lab / "lab.lock").exists() and not list(lab.glob("departure_probe_*")),
          f"a different candidate set is refused before anything is written: {r.stdout[-300:]}")
    return {"refusals": 7}


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
    per = p["period"]
    check(all(x == per["P"] for x in per["gaps"]["bottom"] + per["gaps"]["top"]), f"every gap equals P {per}")
    base = p["baseline"]
    check(base["B"] > dep["D"] and [base["B"], base["target"]] in R["clear"]["breaks"]
          and not any(dep["D"] < t < base["B"] for t, _i in R["clear"]["breaks"]), "B is the first break after D")
    check(base["mask_before"] >> base["target"] & 1 and not base["mask"] >> base["target"] & 1, "the target's bit is cleared at B")
    F = next(t for t in range(dep["C0"], dep["C1"] + 1) if dp.grounded(dp.reply_at(tr, t)))
    w = p["window"]
    check(dep["F"] == F and w["earlier"] == [F, dep["D"], dep["D"] - F + 1] and w["later"] == [dep["D"] + 1, dep["D"] + per["P"], per["P"]], "window")
    onb = [b for b in R["clear"]["breaks"] if dep["C0"] <= b[0] <= dep["D"]]
    check(p["on_group_breaks"] == onb, "the on-group breaks are the clear's breaks inside the contact interval up to D")
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
                   "exit run A", "spans: D", "pre-break departures d", "window start:",
                   "zero native ticks, nothing written", "phase 2 command:", "--expect-digest " + real_plan()["P"]["plan"]["candidate_set_digest"]):
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
