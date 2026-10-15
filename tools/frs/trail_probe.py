#!/usr/bin/env python3
"""Trail-lead probe (lab, exploratory, unregistered): can the search continue from the archive's faster arrivals on the best
verified route's trail, and does it get further from them than from the route's own states at the same cells?

Lead starts: the splice probe's generic rule (docs/frs_splice_probe_2026-10-14.md). The route is the lab import's reference
clear; its burst lineage in the imported archive gives the route's first reach tick j_r at every cell on its trail. A trail cell
whose archive representative arrived strictly earlier (L < j_r) is a lead; the lead start is that representative's stored
prefix (its L words). The paired control is the route's own state at its arrival there: the route's words up to j_r. No cell
id, position, target id, tick value or census number is in this file; everything is read from the import.

Dispatches: k per lead start and k per paired control, with the lab's CONT arm unchanged (rl/frs_worker.run_iterate_frs: the
m8_rd_explore_v1 keyed stream, 120-word segments, at most three continuations under the F3 trigger, read on the imported
archive, which the probe never mutates: no ingest). A lead and its control share one key family,
`<archive id>|trail|<cell>|<burst>:<offset>`, with iteration k, so dispatch k of both plays the same random words from its own
start (common random numbers). Every dispatch is recorded (dispatches.jsonl). Every clear is replayed twice from tick 0 in
fresh processes with the verify flags (rl/frs_verify.verify_twice) after the workers have stopped, and counts only when both
replays agree exactly with each other and with the in-run claim.

    python -B tools/frs/trail_probe.py plan [--lab-root C:/BattleShip_lab] [--out DIR]      zero native ticks: starts, budget, command
    python -B tools/frs/trail_probe.py run  [--lab-root ...] [--out DIR] [--workers 5] [--per-start 10] [--max-ticks 3000000]
                                            [--max-wall-min 75]

Writes only under the output folder (default <lab root>/trail_probe_<date>), through the lab's guard (rl/frs_guard: refuses
the checkout, any runs/ folder and the D: evidence roots; never reads runs/). Readiness uses the registered thresholds, never
lowered. At most 5 workers with one standby each (at most 10 game processes); the verification replays run after the workers
have stopped, at most 5 at once. Process restart resets the episode; every step checks the tick contract. Zero-tick tests:
tools/frs/trail_probe_tests.py. Run with python -B.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "rl"))

import frs_archive as fa  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_machine as fm  # noqa: E402
import frs_report as frep  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_verify as fv  # noqa: E402
import frs_worker as fw  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_rule as mrule  # noqa: E402
import m8_rd_run as mrun  # noqa: E402

PROBE_CONTRACT = "frs_trail_probe_v1"
KEY_FAMILY = "trail"
ARM_NAME = "CONT"
ARM: Dict[str, int] = dict(fr.ARMS[ARM_NAME])                  # segment words, max segments, F3 window: the lab's CONT arm, unchanged
LEAD, CONTROL = "lead", "control"
END_NAMES = {"clear": "clear", "fall": "fall", "length": "out_of_words", "horizon": "horizon", "ended": "ended", "cut": "cut"}
EXIT = {"COMPLETED": 0, "TICK_CAP": 0, "WALL_CAP": 0, "MEMORY_BUDGET": 0, "REFUSED": 2, "PROBE_INVALID": 3, "PROBE_INCOMPLETE": 4}
STATUS_RANK = {"COMPLETED": 0, "TICK_CAP": 1, "WALL_CAP": 1, "MEMORY_BUDGET": 1, "PROBE_INCOMPLETE": 2, "PROBE_INVALID": 3}


class ProbeError(RuntimeError):
    """A violated probe invariant (zero-tick)."""


class Refused(Exception):
    """Open-phase refusal: nothing was launched."""


# -- the reference route and the candidate rule (zero native ticks) -----------------------------------------------------------------


def chain_list(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> List[bytes]:
    """chain[k] = the m8_rd chain digest after input tick k (k = 0: the tick-0 observe record)."""
    ch = [mcell.chain_start(mcell.tick0_record(initial))]
    for s in steps:
        ch.append(mcell.chain_next(ch[-1], mcell.record_digest(mcell.record_of(s))))
    return ch


def load_route(ref_dir: Path, analyse: fv.Analyse) -> Dict[str, Any]:
    """The imported best verified clear (rl/frs_verify.load_reference) plus its stored trace, its chain per tick and its arrival
    tick per level (level n = its n-th break)."""
    R = fv.load_reference(Path(ref_dir), analyse)
    if R["problems"]:
        raise ProbeError(f"reference: {R['problems']}")
    with gzip.open(Path(ref_dir) / "trace.json.gz", "rt", encoding="utf-8") as f:
        trace = json.load(f)
    if trace.get("action_digest") != R["meta"]["native_action_digest"] or len(trace["steps"]) != len(R["words"]):
        raise ProbeError("the stored reference trace does not match the reference words")
    R["trace"] = trace
    R["chain"] = chain_list(trace["initial"], trace["steps"])
    breaks = sorted((int(t), int(i)) for t, i in R["expected"]["breaks"])
    R["arrival"] = {0: 0, **{n + 1: t for n, (t, _i) in enumerate(breaks)}}
    return R


def route_lineage(lab: Any, iteration: int, words: bytes) -> List[Tuple[int, int]]:
    """The route's burst chain [(burst id, words used)] from tick 0: the burst of the route's own iteration whose lineage words
    followed by its own words are exactly the route's words."""
    n = len(words)
    hits = [b for b in lab.bursts if int(b.iteration) == int(iteration) and int(b.start_L) + len(b.words) == n
            and lab.rep_words(*b.start_rep) + bytes(b.words) == words]
    if len(hits) != 1:
        raise ProbeError(f"{len(hits)} archive bursts reproduce the reference route (iteration {iteration})")
    b, o = int(hits[0].id), len(hits[0].words)
    chain: List[Tuple[int, int]] = []
    while b != -1:
        chain.append((b, o))
        b, o = lab.bursts[b].start_rep
        b, o = int(b), int(o)
    return list(reversed(chain))


def trail_of(lab: Any, chain: Sequence[Tuple[int, int]]) -> Tuple[Dict[int, int], Dict[int, Dict[str, Any]]]:
    """(cell id -> the route's first reach tick j_r, cell id -> the route's own win record at that reach, kept when the route's
    arrival was NEW or REPLACE at ingest). Reaches past the words a later lineage burst used are not on the route."""
    first: Dict[int, int] = {}
    wins: Dict[int, Dict[str, Any]] = {}
    L = 0
    for b, o in chain:
        burst = lab.bursts[b]
        if int(burst.start_L) != L:
            raise ProbeError(f"burst {b} starts at {burst.start_L}; the lineage is at {L}")
        for r in burst.reaches:
            j, cid = int(r[0]), int(r[1])
            if j <= L + o and cid not in first:
                first[cid] = j
        for w in burst.wins:
            j, cid = int(w["j"]), int(w["cell"])
            if j <= L + o and first.get(cid) == j and cid not in wins:
                wins[cid] = w
        L += o
    return first, wins


def route_rep_at(lab: Any, chain: Sequence[Tuple[int, int]], tick: int) -> Tuple[int, int]:
    """(burst, offset) of the route's own trajectory at `tick` (informational: the control's 'representative')."""
    for b, o in chain:
        s = int(lab.bursts[b].start_L)
        if s < tick <= s + o:
            return (b, tick - s)
    raise ProbeError(f"tick {tick} is not inside the route's lineage")


def draw_id_of(archive_id: str, cid: int, rep: Sequence[int]) -> str:
    """One key family per lead cell, shared by its lead and its control (common random numbers)."""
    return f"{archive_id}|{KEY_FAMILY}|{int(cid)}|{int(rep[0])}:{int(rep[1])}"


def build_plan(lab: Any, R: Mapping[str, Any]) -> Dict[str, Any]:
    """The starts (lead and paired control per lead cell) and the zero-tick checks of their start records."""
    words, steps, chain = R["words"], R["trace"]["steps"], R["chain"]
    lineage = route_lineage(lab, int(R["meta"]["iteration"]), words)
    first, wins = trail_of(lab, lineage)
    win_check = {"all": [0, 0], "leads": [0, 0]}         # [equal, of]: the control's record at j_r against the route's own win record
    # gain-0 route cells: the representative arrived at the route's own tick. When its words ARE the route's words the stored chain must equal the
    # route's chain; another arrival at the same tick (different words) is reported
    gain0 = {"on_route": [0, 0], "other_arrival": [0, 0]}
    skipped: List[Dict[str, Any]] = []
    starts: List[Dict[str, Any]] = []
    for cid, jr in sorted(first.items(), key=lambda kv: (kv[1], kv[0])):
        c = lab.cells[cid]
        gain = int(jr) - int(c.L)
        step = steps[jr - 1]
        obs = mcell.obs_tuple(step["observation"])
        ed = mcell.record_digest(mcell.record_of(step))
        w = wins.get(cid)
        if w is not None:
            eq = chain[jr].hex() == str(w["ch"]) and ed.hex() == str(w["ed"]) and not mcell.obs_diffs(obs, tuple(w["end"]))
            win_check["all"][1] += 1
            win_check["all"][0] += int(eq)
            if gain >= 1:
                win_check["leads"][1] += 1
                win_check["leads"][0] += int(eq)
        if gain == 0:
            d = gain0["on_route" if lab.rep_words(c.burst, c.offset) == words[:jr] else "other_arrival"]
            d[1] += 1
            d[0] += int(chain[jr] == bytes(c.chain))
        if gain < 1:
            continue
        if c.terminal or jr >= len(words):
            skipped.append({"cid": cid, "route_tick": jr, "why": "terminal representative" if c.terminal else "the route's final tick"})
            continue
        lead_words = lab.cell_words(c)
        rep = (int(c.burst), int(c.offset))
        starts.append({"pair": len(starts), "cid": int(cid), "key": list(c.key), "level": int(c.level), "lead_L": int(c.L), "route_tick": int(jr),
                       "gain": gain, "rep": list(rep), "rep_session": str(lab.bursts[c.burst].session) if c.burst >= 0 else None,
                       "rep_doomed": bool(c.doomed), "draw_id": draw_id_of(lab.archive_id, cid, rep), "control_rep": list(route_rep_at(lab, lineage, jr)),
                       "win_checked": w is not None,
                       LEAD: {"words": lead_words, "end": tuple(c.end), "end_digest": bytes(c.end_digest), "chain": bytes(c.chain),
                              "terminal": bool(c.terminal)},
                       CONTROL: {"words": bytes(words[:jr]), "end": obs, "end_digest": ed, "chain": chain[jr], "terminal": False}})
    per: Dict[str, Dict[str, Any]] = {}
    for cid, jr in first.items():
        per.setdefault(str(lab.cells[cid].level), {"route_cells": 0, "leads": 0, "gains": []})["route_cells"] += 1
    for s in starts:
        p = per[str(s["level"])]
        p["leads"] += 1
        p["gains"].append(s["gain"])
    levels = {lv: {"route_cells": p["route_cells"], "leads": p["leads"], "max_gain": max(p["gains"], default=None),
                   "min_gain": min(p["gains"], default=None)} for lv, p in sorted(per.items(), key=lambda kv: int(kv[0]))}
    digest = hashlib.sha256("".join(f"{s['cid']}:{s['lead_L']}:{s['route_tick']}:{mcell.words_digest(s[LEAD]['words'])}:"
                                    f"{mcell.words_digest(s[CONTROL]['words'])};" for s in starts).encode()).hexdigest()
    exp = R["expected"]
    plan = {"mode": "lab", "contract": PROBE_CONTRACT, "utc": g.utc(), "archive_id": lab.archive_id,
            "rule": "trail_lead_v1: route first reach j_r per trail cell; representative L < j_r is a lead (start = its stored prefix); "
                    "paired control = the route's own words up to j_r; one key family per lead cell shared by both arms",
            "route": {"words": len(words), "digest": R["meta"]["native_action_digest"], "iteration": int(R["meta"]["iteration"]),
                      "completion_input_tick": exp["completion_input_tick"], "completion_time_passed": exp["completion_time_passed"],
                      "final_chain": exp["final_chain"], "breaks": exp["breaks"], "lineage_bursts": len(lineage), "trail_cells": len(first)},
            "arrival_by_level": {str(k): v for k, v in sorted(R["arrival"].items())},
            "leads": len(starts), "skipped": skipped, "per_level": levels, "win_check": win_check, "gain0_stored_chain_equal": gain0,
            "arm": {ARM_NAME: ARM}, "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY, "start_set_digest": digest,
            "prefix_ticks_per_round": sum(s["lead_L"] + s["route_tick"] for s in starts),
            "burst_words_max": ARM["segment_words"] * ARM["max_segments"]}
    return {"plan": plan, "starts": starts, "first": first, "lineage": lineage}


def start_row(s: Mapping[str, Any]) -> Dict[str, Any]:
    """One starts.jsonl row: the start's identity and record digests, without the raw words."""
    out = {k: v for k, v in s.items() if k not in (LEAD, CONTROL)}
    for arm in (LEAD, CONTROL):
        a = s[arm]
        out[arm] = {"words": len(a["words"]), "words_digest": mcell.words_digest(a["words"]), "chain": bytes(a["chain"]).hex(),
                    "end_digest": bytes(a["end_digest"]).hex(), "terminal": bool(a["terminal"])}
    return out


def budget(plan: Mapping[str, Any], per_start: int) -> Dict[str, Any]:
    n = int(plan["leads"])
    d = 2 * per_start * n
    return {"starts": n, "per_start": per_start, "dispatches": d, "prefix_ticks": per_start * int(plan["prefix_ticks_per_round"]),
            "burst_ticks_max": d * int(plan["burst_words_max"]), "reference_ticks": int(plan["route"]["words"]),
            "ticks_max": per_start * int(plan["prefix_ticks_per_round"]) + d * int(plan["burst_words_max"]) + int(plan["route"]["words"])}


def load_all(lab_root: Path, analyse: fv.Analyse = fv.real_analyse) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
    """The imported archive (E6 off, as the lab arms; the Archive6 twin is dropped), its meta (the tick-0 pin) and the route."""
    imp = Path(lab_root) / "import"
    lab, meta, a6 = fa.LabArchive.read_import(imp / "archive", e6=False)
    del a6
    return lab, meta, load_route(imp / "reference", analyse)


# -- per-dispatch readings -------------------------------------------------------------------------------------------------------------


def summarise_result(res: Mapping[str, Any], st: Mapping[str, Any], arm: str, k: int, arrival: Mapping[int, int],
                     trail_by_key: Mapping[Any, int], lab: Any) -> Dict[str, Any]:
    """One dispatches.jsonl row from a finished job: levels reached with their ticks, pace against the route's arrival at each new level
    (positive = ahead), the archive readings of its reaches, the end reason, the words played."""
    L, n, level = int(res["L"]), len(res["words"]), int(st["level"])
    breaks = sorted((int(t), int(i)) for t, i in res["breaks_all"])
    pre = [b for b in breaks if b[0] <= L]
    post = [b for b in breaks if b[0] > L]
    levels = {str(level + i + 1): t for i, (t, _i) in enumerate(post)}
    pace = {lv: int(arrival[int(lv)]) - t for lv, t in levels.items() if int(lv) in arrival}
    new = shorter = ahead = max_gain = max_ahead = 0
    for r in res["reaches"]:
        j, key = int(r[0]), fa.norm_key(r[1])
        cid = lab.by_key.get(key)
        if cid is None:
            new += 1
        else:
            gg = int(lab.cells[cid].L) - j
            if gg > 0:
                shorter += 1
                max_gain = max(max_gain, gg)
        jr = trail_by_key.get(key)
        if jr is not None and jr - j > 0:
            ahead += 1
            max_ahead = max(max_ahead, jr - j)
    end = END_NAMES.get(str(res["end_reason"]), str(res["end_reason"]))
    first_pace = pace.get(str(level + 1))
    rj = res.get("result_json") or {}
    row = {"pair": st["pair"], "cid": st["cid"], "level": level, "arm": arm, "k": k, "draw_id": st["draw_id"], "start_tick": L, "gain": int(st["gain"]),
           "outcome": end, "words_played": n, "ticks": int(res["ticks"]), "deepest": level + len(post), "advanced": len(post) > 0,
           "breaks_after_start": [list(b) for b in post], "levels": levels, "pace": pace, "pace_first": first_pace,
           "delta_first": (first_pace - int(st["gain"])) if first_pace is not None else None, "prefix_breaks": len(pre),
           "prefix_level_ok": len(pre) == level, "reaches": len(res["reaches"]), "new_keys": new, "shortenings": shorter, "max_gain": max_gain,
           "trail_ahead": ahead, "max_ahead": max_ahead, "segments": res.get("segments"), "decisions": res.get("decisions"),
           "tick0_equal": (res.get("tick0") or {}).get("equal"), "prefix_host_frame_equal": (res.get("prefix") or {}).get("host_frame_equal"),
           "mode": res.get("mode"), "worker": res.get("worker"), "wall_s": res.get("wall_s"), "step_s": res.get("step_s"), "ask_s": res.get("ask_s"),
           "words_hex": bytes(res["words"]).hex(), "final_chain": res.get("final_chain") if end == "clear" else None,
           "claimed": {"completion_input_tick": rj.get("completion_input_tick"), "completion_time_passed": rj.get("completion_time_passed")}
           if end == "clear" else None}
    return row


def clear_row(cand: Mapping[str, Any], out: Mapping[str, Any], ref_t: int) -> Dict[str, Any]:
    """One verifications.jsonl row from rl/frs_verify.verify_twice's result: both replays' clocks, chain digests and break tables, the
    verdict, and whether a VERIFIED clear is faster than the reference. Only a VERIFIED row is ever a clear."""
    r1, r2 = out.get("r1") or {}, out.get("r2") or {}
    cit = out.get("completion_input_tick")
    return {"mode": "lab", "kind": "clear", "pair": cand["pair"], "cid": cand["cid"], "level": cand["level"], "arm": cand["arm"], "k": cand["k"],
            "start_tick": cand["start_tick"], "gain": cand["gain"], "words": len(cand["words"]), "words_hex": bytes(cand["words"]).hex(),
            "words_digest": cand["claim"]["words_digest"], "verdict": out["verdict"], "reasons": list(out.get("reasons") or []),
            "completion_input_tick": cit, "completion_time_passed": out.get("completion_time_passed"),
            "chain_r1": r1.get("final_chain"), "chain_r2": r2.get("final_chain"),
            "clocks_r1": [r1.get("completion_input_tick"), r1.get("completion_time_passed")],
            "clocks_r2": [r2.get("completion_input_tick"), r2.get("completion_time_passed")], "breaks_r1": r1.get("breaks"), "breaks_r2": r2.get("breaks"),
            "claim": dict(cand["claim"]), "errors": out.get("errors"), "wall_s": out.get("wall_s"),
            "faster_than_reference": bool(out["verdict"] == fv.VERIFIED and cit is not None and int(cit) < int(ref_t)),
            "reference_completion_input_tick": int(ref_t)}


# -- the engine ----------------------------------------------------------------------------------------------------------------------------


@dataclass
class ProbeConfig:
    lab_root: Path
    out: Path
    run_dir: Path
    per_start: int = 10
    n_workers: int = 5
    max_ticks: int = 3_000_000
    max_wall_s: float = 75 * 60.0
    job_timeout_s: float = mrun.JOB_TIMEOUT_S
    stop_grace_s: float = 60.0
    verify_parallel: int = 5
    mismatch_limit: int = 3
    lifecycle_limit: int = mrule.MAX_LIFECYCLE_FAILURES
    progress_every_s: float = 60.0
    write_reserve_s: float = 30.0
    verify_s_per_clear: float = 30.0         # wall reserved per pending clear (two fresh-process replays); an estimate, never a cap
    verify_floor_s: float = 120.0


class Probe:
    def __init__(self, cfg: ProbeConfig, env: fr.LabEnv, lab: Any, meta: Mapping[str, Any], R: Mapping[str, Any], P: Mapping[str, Any]):
        self.cfg, self.env, self.lab, self.R = cfg, env, lab, R
        self.plan, self.starts = P["plan"], P["starts"]
        self.fs = g.LabFS(cfg.lab_root)
        self.dir = Path(cfg.run_dir)
        self.pin = dict(meta["pin_tick0"])
        self.arrival: Dict[int, int] = {int(k): int(v) for k, v in R["arrival"].items()}
        self.trail_by_key = {fa.norm_key(lab.cells[cid].key): int(jr) for cid, jr in P["first"].items()}
        self.t0 = env.now()
        self.utc_start = g.utc()
        self.phase = "open"
        self.phase_wall: Dict[str, float] = {}
        self.status = "COMPLETED"
        self.stop_reason: Optional[str] = None
        self.stopping = False
        self.notes: List[str] = []
        self.pool: Optional[fr.FrsPool] = None
        self.sampler: Optional[fm.Sampler] = None
        self.queue: Deque[Tuple[int, int, str]] = deque()
        for k in range(cfg.per_start):                      # round k: every start, lead then control; the order alternates per round
            order = list(range(len(self.starts)))
            if k % 2:
                order.reverse()
            for si in order:
                self.queue.append((k, si, LEAD))
                self.queue.append((k, si, CONTROL))
        self.inflight: Dict[int, Dict[str, Any]] = {}
        self.excluded: Dict[int, str] = {}
        self.rows: List[Dict[str, Any]] = []
        self.candidates: List[Dict[str, Any]] = []
        self.vrows: List[Dict[str, Any]] = []
        self.unverified: List[Dict[str, Any]] = []
        self.c = {"dispatches": 0, "jobs": 0, "ticks": 0, "prefix_ticks": 0, "burst_ticks": 0, "reference_ticks": 0, "verify_ticks": 0,
                  "mismatches": 0, "lifecycle_failures": 0, "aborted": 0, "skipped_excluded": 0, "tick0_unequal": 0, "boundaries": 0,
                  "continued": 0}
        self.reserved = 0
        self.reference: Dict[str, Any] = {}
        self.code: Dict[str, str] = {}
        self.code_dig = ""
        self.integrity: Dict[str, Any] = {}
        self._last_progress = self.t0
        self._lock = threading.Lock()

    # -- bookkeeping ----------------------------------------------------------------------------------------------------------------------

    def log(self, s: str) -> None:
        self.env.log(f"trail probe: {s}")
        try:
            self.fs.append_jsonl(self.dir / "run_log.jsonl", {"t_s": round(self.env.now() - self.t0, 1), "phase": self.phase, "msg": s[:2000]})
        except (OSError, g.LabRootError):
            pass

    def mark(self, status: str, reason: str, *, abort: bool = False) -> None:
        if STATUS_RANK[status] > STATUS_RANK[self.status]:
            self.status = status
        self.notes.append(f"{status}: {reason}"[:600])
        if not self.stopping:
            self.stopping = True
            self.stop_reason = reason[:600]
        if abort and self.pool is not None:
            self.pool.abort.set()
        if status != "COMPLETED":
            self.log(f"{status}: {reason}")

    def elapsed(self) -> float:
        return self.env.now() - self.t0

    def used_ticks(self) -> int:
        return self.c["ticks"] + self.c["reference_ticks"] + self.c["verify_ticks"]

    def verify_ticks_pending(self) -> int:
        return 2 * sum(len(c["words"]) for c in self.candidates)

    def dispatch_deadline(self) -> float:
        cfg = self.cfg
        reserve = cfg.stop_grace_s + cfg.write_reserve_s + max(cfg.verify_floor_s, cfg.verify_s_per_clear * (-(-len(self.candidates) // cfg.verify_parallel)))
        return self.t0 + cfg.max_wall_s - reserve

    # -- run ------------------------------------------------------------------------------------------------------------------------------

    def run(self) -> int:
        try:
            self.open()
        except Refused as exc:
            self.fs.write_json(self.cfg.out / f"refused_{g.utc_compact()}.json", {"mode": "lab", "utc": g.utc(), "reason": str(exc)})
            print(f"REFUSED: {exc}", flush=True)
            if self.sampler is not None:
                self.sampler.stop()
            return EXIT["REFUSED"]
        except Exception as exc:  # noqa: BLE001 - an open failure after launching is a closed, reported stop
            self.mark("PROBE_INCOMPLETE", f"open failed: {type(exc).__name__}: {exc}", abort=True)
            self.log(traceback.format_exc()[-2000:])
        else:
            if not self.stopping:
                try:
                    self.dispatch_phase()
                except Exception as exc:  # noqa: BLE001
                    self.mark("PROBE_INCOMPLETE", f"probe error: {type(exc).__name__}: {exc}", abort=True)
                    self.log(traceback.format_exc()[-2000:])
        try:
            self.close()
        except Exception as exc:  # noqa: BLE001
            self.mark("PROBE_INCOMPLETE", f"close error: {type(exc).__name__}: {exc}")
            self.log(traceback.format_exc()[-2000:])
            try:
                self.write_summary()
            except Exception:  # noqa: BLE001
                self.log(traceback.format_exc()[-2000:])
        return EXIT[self.status]

    # -- open -------------------------------------------------------------------------------------------------------------------------------

    def open(self) -> None:
        cfg, env = self.cfg, self.env
        if self.dir.exists():
            raise Refused(f"{self.dir} exists (a run folder is never overwritten)")
        ready = env.readiness()
        if not ready["ok"]:
            raise Refused(f"readiness: {ready['problems']}")
        pids = env.battleship_pids()
        if pids is None or pids:
            raise Refused(f"BattleShip processes already running (or unreadable): {pids}")
        bad = env.import_problems()
        if bad:
            raise Refused(f"import pins: {bad[:6]}")
        if not self.starts:
            raise Refused("no lead start: the route's trail has no earlier arrival in the archive")
        self.fs.mkdir(self.dir)
        self.code = env.code_manifest()
        self.code_dig = fr.code_digest(self.code)
        self.fs.write_json(self.dir / "config.json", self.config_record(ready))
        self.sampler = fm.Sampler(lambda r: self.fs.append_jsonl(self.dir / "memory.jsonl", r), interval=env.sample_s, row_every=env.row_every_s,
                                  caps=env.caps or fm.CAPS_MB, soft=env.soft, snapshot=env.snapshot, now=env.now,
                                  extra=lambda: {"phase": self.phase, "dispatches": self.c["dispatches"], "jobs": self.c["jobs"]}).start()
        self.phase = "reference"
        words = self.R["words"]
        tr, errors = fv.replay_with_retry(env.replay, words, "reference", 0)
        row = fv.evaluate(tr, words, env.analyse)
        fv.save_trace(self.dir / "traces" / "reference.json.gz", tr)
        chk = fv.reference_check(row, self.R)
        self.c["reference_ticks"] += int(row.get("ticks") or 0)
        self.reference = {"ok": bool(chk["ok"]), "differs": chk["differs"], "errors": errors, "completion_input_tick": row.get("completion_input_tick"),
                          "completion_time_passed": row.get("completion_time_passed"), "final_chain": row.get("final_chain"), "ticks": row.get("ticks"),
                          "startup_s": row.get("startup_s"), "stepping_s": row.get("stepping_s")}
        self.fs.write_json(self.dir / "reference.json", self.reference)
        if not chk["ok"]:
            if row.get("outcome") == "error":
                self.mark("PROBE_INCOMPLETE", f"the reference clear could not be replayed: {errors[:2]}")
            else:
                self.mark("PROBE_INVALID", f"the reference clear did not replay exactly: {chk['differs']}")
            return
        self.log(f"reference clear replayed exactly: {row['completion_input_tick']} / {row['completion_time_passed']} in {row.get('stepping_s')} s")
        self.pool = fr.FrsPool(env.worker_spec, env.now)
        self.pool.start(cfg.n_workers)
        self.phase_wall["open"] = round(env.now() - self.t0, 1)
        self.log(f"open done in {self.phase_wall['open']:.0f} s; {cfg.n_workers} workers ready; {len(self.starts)} starts x {cfg.per_start} x 2 = "
                 f"{len(self.queue):,} dispatches queued; arm {ARM_NAME} {ARM}")

    def config_record(self, ready: Mapping[str, Any]) -> Dict[str, Any]:
        c = self.cfg
        return {"mode": "lab", "contract": PROBE_CONTRACT, "utc": g.utc(), "probe_file_sha256": g.sha256_file(Path(__file__).resolve()),
                "lab_code_digest": self.code_dig, "lab_code_files": len(self.code), "arm": ARM_NAME, "arm_params": ARM, "per_start": c.per_start,
                "n_workers": c.n_workers, "max_ticks": c.max_ticks, "max_wall_s": c.max_wall_s, "job_timeout_s": c.job_timeout_s,
                "mismatch_limit": c.mismatch_limit, "lifecycle_limit": c.lifecycle_limit, "verify_parallel": c.verify_parallel,
                "max_battleship_processes": fm.MAX_BATTLESHIP, "memory_caps_mb": dict(self.env.caps or fm.CAPS_MB),
                "memory_soft_budget_mb": dict(self.env.soft or fm.soft_budget(self.env.caps or fm.CAPS_MB)), "readiness": ready,
                "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY, "backend": self.env.backend, "import": str(Path(c.lab_root) / "import"),
                "start_set_digest": self.plan["start_set_digest"], "leads": self.plan["leads"], "budget": budget(self.plan, c.per_start),
                "origins": {"arm": "the lab's CONT arm (rl/frs_run.ARMS), unchanged", "starts": "trail_lead_v1 (this file)",
                            "draw_id": "<archive id>|trail|<cell>|<burst>:<offset>, iteration k: shared by a lead and its control",
                            "caps": "owner, 2026-10-14: at most 75 minutes and 3,000,000 ticks", "readiness": "registered thresholds, never lowered"}}

    # -- dispatch -----------------------------------------------------------------------------------------------------------------------------

    def dispatch_phase(self) -> None:
        cfg, env, pool = self.cfg, self.env, self.pool
        assert pool is not None and self.sampler is not None
        self.phase = "dispatch"
        t = env.now()
        while not self.stopping:
            for w, kind, payload in pool.poll2(0.2, self.on_boundary):
                self.handle(w, kind, payload)
            if self.stopping:
                break
            self.checks()
            if self.stopping:
                break
            for w in pool.idle():
                job = self.next_job(w)
                if job is None:
                    break
                pool.send(w, job)
            self.progress()
        self.phase_wall["dispatch"] = round(env.now() - t, 1)
        self.phase = "drain"
        t = env.now()
        while pool.busy and env.now() - t < cfg.stop_grace_s and not pool.abort.is_set():
            for w, kind, payload in pool.poll2(0.2, self.on_boundary):
                self.handle(w, kind, payload)
        if pool.busy:
            pool.abort.set()
            while pool.busy and env.now() - t < 2 * cfg.stop_grace_s:
                for w, kind, payload in pool.poll2(0.2, self.on_boundary):
                    self.handle(w, kind, payload)
        if pool.busy:
            dead = pool.kill_busy()
            for w in dead:
                self.inflight.pop(w, None)
            self.mark("PROBE_INCOMPLETE", f"workers {dead} did not return after the stop and were terminated")
        self.phase_wall["drain"] = round(env.now() - t, 1)
        self.progress(force=True)

    def checks(self) -> None:
        s, pool, cfg = self.sampler, self.pool, self.cfg
        assert s is not None and pool is not None
        if s.hard_breach:
            self.mark("PROBE_INCOMPLETE", s.hard_breach, abort=True)
        elif s.proc_breach:
            self.mark("PROBE_INCOMPLETE", s.proc_breach, abort=True)
        elif g.LabGuard.violations:
            self.mark("PROBE_INVALID", f"guard violation in the main process: {g.LabGuard.violations[:2]}", abort=True)
        elif s.soft_breach:
            self.mark("MEMORY_BUDGET", s.soft_breach)
        elif self.env.now() >= self.dispatch_deadline():
            self.mark("WALL_CAP", f"the wall cap {cfg.max_wall_s / 60.0:g} min is reached (minus the close reserve)")
        elif pool.oldest_age() > cfg.job_timeout_s:
            self.mark("PROBE_INCOMPLETE", f"a job has been in flight for more than {cfg.job_timeout_s:.0f} s", abort=True)
        elif not [i for i, pr in enumerate(pool.procs) if pr.is_alive() and i not in pool.retired]:
            self.mark("PROBE_INCOMPLETE", "no live worker is left", abort=True)
        elif not self.queue and not pool.busy:
            self.mark("COMPLETED", "every dispatch done")

    def next_job(self, w: int) -> Optional[Dict[str, Any]]:
        cfg = self.cfg
        while self.queue:
            k, si, arm = self.queue[0]
            if si in self.excluded:
                self.queue.popleft()
                self.c["skipped_excluded"] += 1
                continue
            st = self.starts[si]
            sp = st[arm]
            L = len(sp["words"])
            want = L + min(ARM["segment_words"] * ARM["max_segments"], mcell.HORIZON - L)
            if self.used_ticks() + self.reserved + want + self.verify_ticks_pending() > cfg.max_ticks:
                self.mark("TICK_CAP", f"the tick cap {cfg.max_ticks:,} would be exceeded by the next dispatch")
                return None
            self.queue.popleft()
            job = {"kind": fw.JOB_KIND, "iteration": k, "cell": st["cid"], "rep": tuple(st["rep"] if arm == LEAD else st["control_rep"]),
                   "words": bytes(sp["words"]), "end": tuple(sp["end"]), "end_digest": bytes(sp["end_digest"]), "chain": bytes(sp["chain"]),
                   "terminal": bool(sp["terminal"]), "pin": self.pin, "archive_id": st["draw_id"], "allowance": want, **ARM}
            self.inflight[w] = {"si": si, "arm": arm, "k": k, "reserved": want, "cont": []}
            self.reserved += want
            self.c["dispatches"] += 1
            return job
        return None

    def on_boundary(self, w: int, payload: Dict[str, Any]) -> None:
        info = self.inflight.get(w)
        aborting = self.pool is not None and self.pool.abort.is_set()
        if aborting or info is None or info["k"] != int(payload["iteration"]):
            d: Dict[str, Any] = {"go": False, "stopping": True}
        else:
            d = self.lab.continuation_decision(payload["reaches"])
        go = bool(d["go"])
        self.c["boundaries"] += 1
        self.c["continued"] += int(go)
        if info is not None:
            info["cont"].append([int(payload["segment"]), len(payload["reaches"]), d.get("new"), d.get("shorter"), d.get("max_gain"), int(go)])
        try:
            self.pool.conns[w].send(("continue", {"iteration": payload["iteration"], "segment": payload["segment"], "go": go}))
        except (OSError, BrokenPipeError):
            pass

    def emit(self, row: Dict[str, Any]) -> None:
        with self._lock:
            self.rows.append(row)
            self.fs.append_jsonl(self.dir / "dispatches.jsonl", row)

    def handle(self, w: int, kind: str, payload: Dict[str, Any]) -> None:
        info = self.inflight.pop(w, None)
        if info is not None:
            self.reserved -= info["reserved"]
        if kind in ("died", "fatal"):
            self.mark("PROBE_INCOMPLETE", f"worker {w} {kind}: {json.dumps(payload, default=str)[:300]}", abort=True)
            return
        if payload.get("guard_violations") or payload.get("provenance_violations"):
            self.mark("PROBE_INVALID", f"worker {w} guard / provenance violation: "
                                       f"{(payload.get('guard_violations') or payload.get('provenance_violations'))[:2]}", abort=True)
        if info is None:
            self.mark("PROBE_INVALID", f"worker {w} returned a job that was not in flight")
            return
        st, arm, k = self.starts[info["si"]], info["arm"], info["k"]
        if payload.get("ok"):
            self.commit(info, payload)
            return
        kd = payload.get("kind")
        base = {"pair": st["pair"], "cid": st["cid"], "level": st["level"], "arm": arm, "k": k, "draw_id": st["draw_id"],
                "start_tick": len(st[arm]["words"]), "gain": st["gain"], "advanced": False, "deepest": st["level"], "ticks": 0, "words_played": 0}
        if kd == "mismatch":
            self.emit(dict(base, outcome="mismatch", mismatch=payload.get("mismatch"), detail=json.dumps(payload.get("detail"), default=str)[:800]))
            if payload.get("mismatch") in fa.QUARANTINE_KINDS:
                self.c["mismatches"] += 1
                self.excluded[info["si"]] = f"{arm} prefix {payload.get('mismatch')}"
                self.log(f"pair {st['pair']} (cell {st['cid']}) excluded: the {arm} prefix did not reproduce ({payload.get('mismatch')})")
                if self.c["mismatches"] > self.cfg.mismatch_limit:
                    self.mark("PROBE_INVALID", f"{self.c['mismatches']} prefix mismatches > {self.cfg.mismatch_limit}", abort=True)
            else:
                self.mark("PROBE_INVALID", f"pair {st['pair']} {arm} k {k}: mismatch {payload.get('mismatch')} "
                                           f"{json.dumps(payload.get('detail'), default=str)[:400]}", abort=True)
        elif kd == "lifecycle":
            self.c["lifecycle_failures"] += 1
            self.emit(dict(base, outcome="lifecycle", detail=str(payload.get("message"))[:300]))
            self.log(f"lifecycle failure {payload.get('outcome')} on worker {w}: {str(payload.get('message'))[:200]}")
            if self.c["lifecycle_failures"] > self.cfg.lifecycle_limit:
                self.mark("PROBE_INCOMPLETE", f"more than {self.cfg.lifecycle_limit} lifecycle failures", abort=True)
        elif kd == "aborted":
            self.c["aborted"] += 1
            self.emit(dict(base, outcome="aborted"))
        else:
            self.mark("PROBE_INCOMPLETE", f"worker {w} error: {str(payload.get('error'))[:300]}", abort=True)
            self.log(str(payload.get("trace", ""))[-1500:])

    def commit(self, info: Mapping[str, Any], res: Mapping[str, Any]) -> None:
        st, arm, k = self.starts[info["si"]], info["arm"], info["k"]
        row = summarise_result(res, st, arm, k, self.arrival, self.trail_by_key, self.lab)
        row["cont"] = list(info["cont"])
        n = len(res["words"])
        self.c["jobs"] += 1
        self.c["ticks"] += int(res["ticks"])
        self.c["burst_ticks"] += n
        self.c["prefix_ticks"] += int(res["ticks"]) - n
        if not (res.get("tick0") or {}).get("equal", True):
            self.c["tick0_unequal"] += 1
        self.emit(row)
        if row["outcome"] == "clear" and n > 0:
            words = bytes(st[arm]["words"]) + bytes(res["words"])
            claim = {"words_digest": mcell.words_digest(words), "completion_input_tick": row["claimed"]["completion_input_tick"],
                     "completion_time_passed": row["claimed"]["completion_time_passed"], "chain": res.get("final_chain")}
            self.candidates.append({"pair": st["pair"], "cid": st["cid"], "level": st["level"], "arm": arm, "k": k, "words": words, "claim": claim,
                                    "start_tick": row["start_tick"], "gain": row["gain"]})
            self.log(f"clear candidate: pair {st['pair']} {arm} k {k}, {len(words):,} words (claimed {claim['completion_input_tick']} / "
                     f"{claim['completion_time_passed']}); verified after the workers stop")

    def progress(self, force: bool = False) -> None:
        now = self.env.now()
        if not force and now - self._last_progress < self.cfg.progress_every_s:
            return
        self._last_progress = now
        adv = sum(1 for r in self.rows if r.get("advanced"))
        mb = (self.sampler.last or {}).get("main_private_mb") if self.sampler else None
        self.log(f"t {self.elapsed():.0f}s dispatches {self.c['dispatches']:,} jobs {self.c['jobs']:,} advanced {adv:,} ticks {self.used_ticks():,} "
                 f"(prefix {self.c['prefix_ticks']:,} burst {self.c['burst_ticks']:,}) cont {self.c['continued']}/{self.c['boundaries']} "
                 f"clear candidates {len(self.candidates)} excluded {len(self.excluded)} queued {len(self.queue):,} in flight "
                 f"{len(self.pool.busy) if self.pool else 0} main MB {mb}")
        try:
            self.fs.write_json(self.dir / "state.json", {"mode": "lab", "utc": g.utc(), "phase": self.phase, "elapsed_s": round(self.elapsed(), 1),
                                                          "counters": self.c, "status": self.status, "stop": self.stop_reason, "queued": len(self.queue),
                                                          "candidates": len(self.candidates), "verifications": len(self.vrows)})
        except OSError:
            pass

    # -- close: the workers stop, then every clear candidate is verified twice from tick 0 ------------------------------------------------

    def close(self) -> None:
        cfg, env = self.cfg, self.env
        self.phase = "close"
        t = env.now()
        if self.pool is not None:
            self.pool.stop(grace=60.0)
        left = env.wait_no_battleship(60.0)
        self.verify_all()
        changed = [rel for rel, h in self.code.items() if (g.REPO / rel).is_file() and g.sha256_file(g.REPO / rel) != h]
        self.integrity.update({"guard_violations_main": list(g.LabGuard.violations)[:5], "lab_code_changed_during_run": changed,
                               "battleship_left": left, "tick0_unequal_jobs": self.c["tick0_unequal"], "prefix_mismatches": self.c["mismatches"],
                               "excluded_pairs": dict(self.excluded), "reference_ok": self.reference.get("ok"),
                               "prefix_level_ok_all": all(r.get("prefix_level_ok", True) for r in self.rows)})
        if left:
            self.mark("PROBE_INCOMPLETE", f"BattleShip processes still alive after the close: {left}")
        self.phase_wall["close"] = round(env.now() - t, 1)
        self.write_summary()
        self.log(f"done: {self.status} ({self.stop_reason}); summary {self.dir / 'summary.json'}")

    def verify_candidate(self, cand: Mapping[str, Any], slot: int) -> Dict[str, Any]:
        label = f"clear_p{cand['pair']}_{cand['arm']}_k{cand['k']}"
        try:
            out = fv.verify_twice(self.env.replay, self.env.analyse, cand["words"], cand["claim"], label, slot, trace_dir=self.dir / "traces")
        except Exception as exc:  # noqa: BLE001 - a crashed verification is an ERROR row, never a clear
            out = {"label": label, "verdict": fv.ERROR, "reasons": [f"{type(exc).__name__}: {exc}"[:300]], "r1": {}, "r2": {}, "errors": [],
                   "words": len(cand["words"]), "wall_s": None}
        return out

    def on_verified(self, cand: Mapping[str, Any], out: Mapping[str, Any]) -> None:
        r1, r2 = out.get("r1") or {}, out.get("r2") or {}
        self.c["verify_ticks"] += int(r1.get("ticks") or 0) + int(r2.get("ticks") or 0)
        row = clear_row(cand, out, int(self.R["expected"]["completion_input_tick"]))
        row["utc"] = g.utc()
        self.vrows.append(row)
        self.fs.append_jsonl(self.dir / "verifications.jsonl", row)
        self.log(f"verification of pair {cand['pair']} {cand['arm']} k {cand['k']}: {out['verdict']} {out.get('completion_input_tick')} / "
                 f"{out.get('completion_time_passed')} (reference {row['reference_completion_input_tick']})")
        if out["verdict"] == fv.NONDETERMINISTIC:
            self.mark("PROBE_INVALID", f"pair {cand['pair']} {cand['arm']} k {cand['k']}: a claimed clear did not replay exactly: {row['reasons'][:2]}")

    def verify_all(self) -> None:
        """Every clear candidate, up to verify_parallel at once (no worker is alive now), before the wall deadline."""
        deadline = self.t0 + self.cfg.max_wall_s - self.cfg.write_reserve_s
        if not self.candidates:
            return
        self.phase = "verify"
        lock = threading.Lock()
        queue = sorted(self.candidates, key=lambda c: (c["claim"]["completion_input_tick"] or 10 ** 9, c["pair"], c["arm"], c["k"]))
        results: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

        def worker(slot: int) -> None:
            while True:
                with lock:
                    if not queue or self.env.now() >= deadline:
                        return
                    cand = queue.pop(0)
                out = self.verify_candidate(cand, slot)
                with lock:
                    results.append((cand, out))

        n = max(1, min(self.cfg.verify_parallel, len(queue)))
        ths = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
        for th in ths:
            th.start()
        for th in ths:
            th.join(timeout=max(1.0, deadline - self.env.now() + 180.0))
        for cand, out in results:
            self.on_verified(cand, out)
        self.unverified = [{"pair": c["pair"], "arm": c["arm"], "k": c["k"], "words": len(c["words"]), "claim": c["claim"]} for c in queue]
        if self.unverified:
            self.log(f"{len(self.unverified)} clear candidates NOT verified before the deadline (never clears)")

    # -- the summary ------------------------------------------------------------------------------------------------------------------------

    def write_summary(self) -> Dict[str, Any]:
        mem = self.sampler.stop() if self.sampler is not None else {}
        s = summarise_rows(self.rows, self.vrows, self.starts, self.R)
        s.update({"mode": "lab", "contract": PROBE_CONTRACT, "status": self.status, "stop": {"reason": self.stop_reason, "notes": self.notes[:12]},
                  "utc_start": self.utc_start, "utc_end": g.utc(), "folder": str(self.dir), "phase_wall_s": dict(self.phase_wall),
                  "elapsed_s": round(self.elapsed(), 1), "config": {"per_start": self.cfg.per_start, "n_workers": self.cfg.n_workers,
                                                                      "max_ticks": self.cfg.max_ticks, "max_wall_s": self.cfg.max_wall_s, "arm": ARM_NAME,
                                                                      **ARM, "lab_code_digest": self.code_dig, "backend": self.env.backend,
                                                                      "start_set_digest": self.plan["start_set_digest"]},
                  "work": dict(self.c, ticks_total=self.used_ticks(), queued_left=len(self.queue), excluded_pairs=len(self.excluded)),
                  "reference": self.reference, "unverified": self.unverified,
                  "memory": {"peak": mem.get("peak"), "soft_breach": mem.get("soft_breach"), "hard_breach": mem.get("hard_breach"),
                             "proc_breach": mem.get("proc_breach"), "soft_budget_mb": mem.get("soft_budget_mb")},
                  "integrity": self.integrity})
        self.fs.write_text(self.dir / "summary.json", frep.compact_json(s), atomic=True)
        self.fs.write_text(self.dir / "report.md", report_md(s), atomic=True)
        return s


def summarise_rows(rows: Sequence[Mapping[str, Any]], vrows: Sequence[Mapping[str, Any]], starts: Sequence[Mapping[str, Any]],
                   R: Mapping[str, Any]) -> Dict[str, Any]:
    """Per start level and arm: dispatches, the share that advanced a level, the deepest reach, the pace at the first new level (mean, best)
    and its change against the start's own lead; the leads that went furthest; the pairs compared; the verified clears."""
    per: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        d = per.setdefault(str(r["level"]), {}).setdefault(r["arm"], {"dispatches": 0, "jobs": 0, "advanced": 0, "deepest": int(r["level"]),
                                                                       "pace_first": [], "delta_first": [], "clears": 0, "falls": 0, "out_of_words": 0,
                                                                       "horizon": 0, "other": 0, "shortenings": 0, "trail_ahead": 0, "new_keys": 0,
                                                                       "continued": 0, "boundaries": 0})
        d["dispatches"] += 1
        if r.get("outcome") in ("mismatch", "lifecycle", "aborted"):
            d["other"] += 1
            continue
        d["jobs"] += 1
        d["advanced"] += int(bool(r.get("advanced")))
        d["deepest"] = max(d["deepest"], int(r.get("deepest", r["level"])))
        if r.get("pace_first") is not None:
            d["pace_first"].append(int(r["pace_first"]))
            d["delta_first"].append(int(r["delta_first"]))
        d["clears"] += int(r.get("outcome") == "clear")
        d["falls"] += int(r.get("outcome") == "fall")
        d["out_of_words"] += int(r.get("outcome") == "out_of_words")
        d["horizon"] += int(r.get("outcome") == "horizon")
        d["shortenings"] += int(r.get("shortenings") or 0)
        d["trail_ahead"] += int(r.get("trail_ahead") or 0)
        d["new_keys"] += int(r.get("new_keys") or 0)
        for c in r.get("cont") or []:
            d["boundaries"] += 1
            d["continued"] += int(c[-1])
    out_levels: Dict[str, Dict[str, Any]] = {}
    for lv, arms in sorted(per.items(), key=lambda kv: int(kv[0])):
        out_levels[lv] = {}
        for arm, d in arms.items():
            pf, df = d.pop("pace_first"), d.pop("delta_first")
            out_levels[lv][arm] = dict(d, advanced_share=round(d["advanced"] / d["jobs"], 4) if d["jobs"] else None,
                                       pace_first_mean=round(sum(pf) / len(pf), 1) if pf else None, pace_first_best=max(pf) if pf else None,
                                       delta_first_mean=round(sum(df) / len(df), 1) if df else None, delta_first_best=max(df) if df else None)
    pairs: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        if r.get("outcome") in ("mismatch", "lifecycle", "aborted"):
            continue
        p = pairs.setdefault(int(r["pair"]), {"cid": r["cid"], "level": r["level"], "gain": r["gain"], LEAD: [0, int(r["level"]), None], CONTROL: [0, int(r["level"]), None]})
        a = p[r["arm"]]
        a[0] += 1
        a[1] = max(a[1], int(r.get("deepest", r["level"])))
        if r.get("pace_first") is not None:
            a[2] = max(a[2], int(r["pace_first"])) if a[2] is not None else int(r["pace_first"])
    cmp = {"pairs": len(pairs), "lead_deeper": 0, "equal": 0, "control_deeper": 0, "lead_only_advanced": 0, "control_only_advanced": 0, "both_advanced": 0}
    for p in pairs.values():
        ld, cd = p[LEAD][1], p[CONTROL][1]
        cmp["lead_deeper" if ld > cd else "control_deeper" if cd > ld else "equal"] += 1
        la, ca = ld > p["level"], cd > p["level"]
        if la and ca:
            cmp["both_advanced"] += 1
        elif la:
            cmp["lead_only_advanced"] += 1
        elif ca:
            cmp["control_only_advanced"] += 1
    leads = [r for r in rows if r["arm"] == LEAD and r.get("advanced")]
    leads.sort(key=lambda r: (-int(r["deepest"]), -(max(r["pace"].values()) if r.get("pace") else -10 ** 9), int(r["pair"]), int(r["k"])))
    furthest = [{k: r.get(k) for k in ("pair", "cid", "level", "k", "start_tick", "gain", "deepest", "levels", "pace", "outcome", "words_played",
                                       "shortenings", "trail_ahead", "max_ahead")} for r in leads[:12]]
    verified = [v for v in vrows if v["verdict"] == fv.VERIFIED]
    ref_t = int(R["expected"]["completion_input_tick"])
    best = min(verified, key=lambda v: (v["completion_input_tick"], v["completion_time_passed"]), default=None)
    return {"per_level": out_levels, "pairs": cmp, "furthest_leads": furthest,
            "clears": {"candidates": len(vrows), "verified": len(verified), "faster_than_reference": sum(1 for v in verified if v["faster_than_reference"]),
                       "reference_completion_input_tick": ref_t,
                       "best_verified": None if best is None else {k: best[k] for k in ("pair", "arm", "k", "completion_input_tick", "completion_time_passed",
                                                                                          "chain_r1", "chain_r2", "words_digest")},
                       "rows": [{k: v.get(k) for k in ("pair", "cid", "level", "arm", "k", "start_tick", "gain", "words", "verdict", "completion_input_tick",
                                                       "completion_time_passed", "chain_r1", "chain_r2", "clocks_r1", "clocks_r2", "words_digest",
                                                       "faster_than_reference", "reasons")} for v in vrows]},
            "starts": len(starts)}


def report_md(s: Mapping[str, Any]) -> str:
    w, cl = s["work"], s["clears"]
    lines: List[str] = [f"# Trail-lead probe run ({s['utc_start'][:10]})", "",
                        f"Lab, exploratory, unregistered (mode lab). Status **{s['status']}** ({s['stop']['reason']}). Arm {s['config']['arm']} "
                        f"(segments {s['config']['segment_words']} x {s['config']['max_segments']}, F3 window {s['config']['window']}); {s['starts']} starts x "
                        f"{s['config']['per_start']} x 2 arms.", "",
                        "| measure | value |", "|---|---|",
                        f"| wall / open / dispatch / drain / close | {frep.fmt(s['elapsed_s'], 0)} s / {frep.fmt(s['phase_wall_s'].get('open'), 0)} s / "
                        f"{frep.fmt(s['phase_wall_s'].get('dispatch'), 0)} s / {frep.fmt(s['phase_wall_s'].get('drain'), 0)} s / "
                        f"{frep.fmt(s['phase_wall_s'].get('close'), 0)} s |",
                        f"| dispatches / jobs / queued left / excluded pairs | {frep.fmt(w['dispatches'])} / {frep.fmt(w['jobs'])} / {frep.fmt(w['queued_left'])} / "
                        f"{w['excluded_pairs']} |",
                        f"| ticks: total / dispatch prefix / burst / reference / verification | {frep.fmt(w['ticks_total'])} / {frep.fmt(w['prefix_ticks'])} / "
                        f"{frep.fmt(w['burst_ticks'])} / {frep.fmt(w['reference_ticks'])} / {frep.fmt(w['verify_ticks'])} |",
                        f"| continuation: boundaries / continued | {w['boundaries']} / {w['continued']} |",
                        f"| reference clear replayed exactly at open | {s['reference'].get('ok')} ({frep.fmt(s['reference'].get('completion_input_tick'))} / "
                        f"{frep.fmt(s['reference'].get('completion_time_passed'))}) |",
                        f"| clear candidates / verified / faster than the reference ({frep.fmt(cl['reference_completion_input_tick'])}) | "
                        f"{cl['candidates']} / {cl['verified']} / {cl['faster_than_reference']} |",
                        f"| pairs: lead deeper / equal / control deeper | {s['pairs']['lead_deeper']} / {s['pairs']['equal']} / {s['pairs']['control_deeper']} "
                        f"(of {s['pairs']['pairs']}) |",
                        f"| main process MB peak / BattleShip peak | {frep.fmt((s['memory'].get('peak') or {}).get('main_private_mb'), 0)} / "
                        f"{(s['memory'].get('peak') or {}).get('battleship')} |",
                        "", "Per start level, lead against control (pace = the route's arrival at the new level minus the dispatch's; delta = pace minus the "
                        "start's own lead):", "",
                        "| level | arm | jobs | advanced | share | deepest | pace first mean / best | delta first mean / best | clears | falls | out of words "
                        "| horizon | shortenings | trail ahead | continued / boundaries |",
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for lv, arms in s["per_level"].items():
        for arm in (LEAD, CONTROL):
            d = arms.get(arm)
            if d is None:
                continue
            lines.append(f"| {lv} | {arm} | {d['jobs']} | {d['advanced']} | {frep.fmt(d['advanced_share'], 3)} | {d['deepest']} | "
                         f"{frep.fmt(d['pace_first_mean'], 1)} / {frep.fmt(d['pace_first_best'])} | {frep.fmt(d['delta_first_mean'], 1)} / "
                         f"{frep.fmt(d['delta_first_best'])} | {d['clears']} | {d['falls']} | {d['out_of_words']} | {d['horizon']} | {d['shortenings']} | "
                         f"{d['trail_ahead']} | {d['continued']} / {d['boundaries']} |")
    lines += ["", "Leads that went furthest (deepest level, then best pace):", "",
              "| pair | cell | level | k | start | lead | deepest | levels (tick) | pace | outcome | words |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in s["furthest_leads"]:
        lines.append(f"| {r['pair']} | {r['cid']} | {r['level']} | {r['k']} | {frep.fmt(r['start_tick'])} | {r['gain']} | {r['deepest']} | "
                     f"{json.dumps(r['levels'])} | {json.dumps(r['pace'])} | {r['outcome']} | {r['words_played']} |")
    lines += ["", "Clears (every candidate, replayed twice from tick 0 in fresh processes with the verify flags; a clear counts only when VERIFIED):", "",
              "| pair | arm | k | level | start | verdict | replay 1 clocks | replay 2 clocks | replay 1 chain | replay 2 chain | faster than reference |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for v in cl["rows"]:
        lines.append(f"| {v['pair']} | {v['arm']} | {v['k']} | {v['level']} | {frep.fmt(v['start_tick'])} | {v['verdict']} | "
                     f"{frep.fmt(v['clocks_r1'][0])} / {frep.fmt(v['clocks_r1'][1])} | {frep.fmt(v['clocks_r2'][0])} / {frep.fmt(v['clocks_r2'][1])} | "
                     f"`{v['chain_r1']}` | `{v['chain_r2']}` | {v['faster_than_reference']} |")
    if s.get("unverified"):
        lines.append(f"\nCandidates NOT verified before the deadline (never clears): {json.dumps(s['unverified'], default=str)[:600]}")
    lines += ["", f"Integrity: {json.dumps(s['integrity'], separators=(',', ':'), default=str)}", ""]
    return "\n".join(lines)


# -- commands --------------------------------------------------------------------------------------------------------------------------------


def plan_and_write(lab_root: Path, out: Path, analyse: fv.Analyse = fv.real_analyse) -> Dict[str, Any]:
    """Zero native ticks: the starts and their checks, written as plan.json and starts.jsonl (a different start set is never overwritten)."""
    lab, meta, R = load_all(lab_root, analyse)
    P = build_plan(lab, R)
    fs = g.LabFS(lab_root)
    saved = Path(out) / "plan.json"
    if saved.is_file():
        old = json.loads(saved.read_text(encoding="utf-8"))
        if old.get("start_set_digest") != P["plan"]["start_set_digest"]:
            raise ProbeError(f"refused: {saved} exists with a different start set ({str(old.get('start_set_digest'))[:16]})")
    fs.mkdir(Path(out))
    fs.write_json(saved, P["plan"])
    fs.write_text(Path(out) / "starts.jsonl", "".join(json.dumps(start_row(s), separators=(",", ":"), default=str) + "\n" for s in P["starts"]))
    return {"lab": lab, "meta": meta, "R": R, "P": P}


def run_command(lab_root: Path, out: Path, a: argparse.Namespace) -> str:
    return (f"python -B tools/frs/trail_probe.py run --lab-root {Path(lab_root).as_posix()} --out {Path(out).as_posix()} --workers {a.workers} "
            f"--per-start {a.per_start} --max-ticks {a.max_ticks} --max-wall-min {a.max_wall_min:g}")


def cmd_plan(lab_root: Path, out: Path, a: argparse.Namespace) -> int:
    L = plan_and_write(lab_root, out)
    p = L["P"]["plan"]
    b = budget(p, a.per_start)
    print(json.dumps({k: p[k] for k in ("leads", "win_check", "gain0_stored_chain_equal", "skipped", "start_set_digest")}, separators=(",", ":")))
    print(json.dumps({"route": {k: p["route"][k] for k in ("words", "completion_input_tick", "completion_time_passed", "lineage_bursts", "trail_cells")}},
                     separators=(",", ":")))
    for lv, d in p["per_level"].items():
        print("level", lv, json.dumps(d, separators=(",", ":")))
    print("budget", json.dumps(b, separators=(",", ":")))
    print(f"wrote {Path(out) / 'plan.json'} and {Path(out) / 'starts.jsonl'}")
    print("run with:", run_command(lab_root, out, a))
    return 0


def cmd_run(lab_root: Path, out: Path, a: argparse.Namespace) -> int:
    import frs_lab as fl
    from m7_runtime import install_kill_on_close_job

    run_dir = Path(out) / "run"
    if run_dir.exists():
        print(f"refused: {run_dir} exists (never overwritten)")
        return 2
    saved = Path(out) / "plan.json"
    if not saved.is_file():
        print(f"refused: no {saved}: run `plan` first")
        return 2
    lab, meta, R = load_all(lab_root)
    P = build_plan(lab, R)
    if json.loads(saved.read_text(encoding="utf-8")).get("start_set_digest") != P["plan"]["start_set_digest"]:
        print("refused: the start set differs from the saved plan")
        return 2
    install_kill_on_close_job()
    cfg = ProbeConfig(lab_root=Path(lab_root), out=Path(out), run_dir=run_dir, per_start=a.per_start, n_workers=a.workers, max_ticks=a.max_ticks,
                      max_wall_s=60.0 * a.max_wall_min)
    code = Probe(cfg, fl.real_env(Path(lab_root), run_dir), lab, meta, R, P).run()
    print(f"exit {code}: {run_dir / 'report.md'}")
    return code


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("command", choices=("plan", "run"))
    ap.add_argument("--lab-root", default=str(g.DEFAULT_LAB_ROOT))
    ap.add_argument("--out", default=None, help="default <lab root>/trail_probe_<date>")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--per-start", type=int, default=10)
    ap.add_argument("--max-ticks", type=int, default=3_000_000)
    ap.add_argument("--max-wall-min", type=float, default=75.0)
    a = ap.parse_args(argv)
    try:
        lab = g.validate_lab_root(Path(a.lab_root))
        out = g.validate_run_dir(Path(a.out) if a.out else lab / f"trail_probe_{dt.date.today().isoformat()}", lab)
    except g.LabRootError as exc:
        raise SystemExit(str(exc))
    if not 1 <= a.workers <= 5:
        raise SystemExit("refused: 1 to 5 workers (one standby each: at most 10 game processes)")
    if a.per_start < 1 or a.max_ticks < 1 or a.max_wall_min <= 0:
        raise SystemExit("refused: --per-start, --max-ticks and --max-wall-min are positive")
    if not (lab / "import" / "import_manifest.json").is_file():
        raise SystemExit("refused: no lab import (rl/frs_lab.py import first)")
    g.LabGuard.install(lab)
    lock = g.LabLock(lab, f"trail_probe {a.command}")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        print(str(exc))
        return 2
    try:
        if a.command == "plan":
            return cmd_plan(lab, out, a)
        return cmd_run(lab, out, a)
    except ProbeError as exc:
        print(str(exc))
        return 3
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
