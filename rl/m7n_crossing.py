"""M7n gate-2 inputs: replay-verified qualified wall crossings and left-target breaks (`m7n_crossing_verification_v1`,
criterion `btt_qualified_crossing_v1`), for the v3 finals AND the control finals with one code path.

Why (pre-launch correction 1, 2026-09-26): a live x < -2100 entry alone is diagnostic only. M7h showed that an off-stage
fall (s2 56a1af09, y -8412) satisfies the raw left-region rule. Gate 2 therefore needs, per final stochastic label:

  candidates   every stochastic episode of the label whose btt_eval_metrics_v1 record has a first_left_entry or a
               left target (1, 6, 8) among broken_ids (the deterministic play stays diagnostic, as for T);
  replay       each candidate's canonical native actions resubmitted from tick 0 on a fresh process (m7f_trace
               stepping trace, read-only native diagnostics on); EXACT iff no consumed-tick mismatch, every action
               consumed, the replayed native action digest equals the record's, the replayed break table (id, tick)
               equals the recorded target_breaks and the replayed first left entry tick equals the recorded one;
               a candidate that does not replay exactly is an integrity problem (never counted, never ignored);
  qualified wall crossing  on the exact trace, an ENTRY (a live step E whose immediately preceding live step P has
               x_P >= -2100 > x_E; the tick-0 reset observation is the predecessor of step 0; btt_reward_v3's pairing)
               whose class is over_wall (btt_reward_v3.classify_entry: y at x = -2100 >= wall_top_y - 1 = 2999; an
               under_stage or through_face entry is an off-stage fall / anomaly, never a crossing), on a trace whose
               btt_crossing_evidence_v1 path is over_ledge (Mario at or above the wall top over the ledge span between
               the grounded takeoff and the first left step) with a grounded takeoff (approach_surface present),
               FOLLOWED, inside the same left visit (before the next exit x >= -2100), by a VALID LEFT-SIDE LANDING:
               a live grounded step (ground_air_state 0) that m7g_fixture.classify_ground matches to a decoded
               left-side floor line (derived left_side_floor_lines: line 3 on Mario's stage, y -1950, x -3900..-2700,
               tolerance 1.0) and that is not the native-failure step itself. The route label of the crossing
               (btt_route_rule_v1: lower_precision / upper_moving_platform / unclassified) and whether the right
               sweep was complete at the entry are RECORDED, never required (the M7g-a decision: the route classifier
               proposes, it never gates).
  left-target break  a candidate whose exact replay's break table contains target 1, 6 or 8.
  X            1 iff the label has >= 1 qualified crossing episode or >= 1 verified left-target-break episode.

Pure parts (analyse_trace, candidates, crossing_inputs, self_test) need no game; verify_crossings_in replays.

    python rl/m7n_crossing.py self-test
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7g_fixture as fx  # noqa: E402
from btt_reward_v3 import OVER_WALL, UNPAIRED, classify_entry  # noqa: E402
from btt_rewards import REWARD_V3  # noqa: E402

REPO_ROOT = RL_DIR.parent
CONTRACT = "m7n_crossing_verification_v1"
CRITERION = "btt_qualified_crossing_v1"
LEFT_TARGET_IDS = tuple(fx.LEFT_TARGET_IDS)          # (1, 6, 8)
REPLAY_FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_TARGET_DIAG": "1"}
REPLAY_INDEX_BASE = 9800

_GEO: Optional[fx.StageGeometry] = None


def geometry() -> fx.StageGeometry:
    global _GEO
    if _GEO is None:
        geo = fx.decode_stage_geometry()
        geo.derived = fx.derive_regions(geo)
        _GEO = geo
    return _GEO


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def criterion_description() -> Dict[str, Any]:
    d = geometry().derived
    return {
        "criterion": CRITERION, "contract": CONTRACT,
        "candidates": "final stochastic episodes with a btt_eval_metrics_v1 first_left_entry or a left target (1, 6, 8) in broken_ids",
        "replay": "canonical native actions from tick 0 on a fresh process (rl/m7f_trace.run_stepping_trace); flags "
                  + json.dumps(REPLAY_FLAGS, sort_keys=True),
        "exact": ["consumed_tick_mismatch is None", "unsent == 0", "replayed native action digest == recorded",
                  "replayed break table (id, consumed_tick) == recorded target_breaks",
                  "replayed first left entry consumed tick == recorded (both None or equal)"],
        "entry": "a live step E whose immediately preceding live step P has x_P >= left_boundary_x > x_E (the tick-0 "
                 "observation is the predecessor of step 0); btt_reward_v3.classify_entry gives over_wall iff the y "
                 "interpolated at the boundary is >= wall_top_y - entry_y_tolerance",
        "qualified_wall_crossing": "entry class over_wall AND btt_crossing_evidence_v1 crossing_path == over_ledge AND a "
                                   "grounded takeoff (approach_surface) AND a valid left-side landing inside the same left "
                                   "visit (before the next exit)",
        "valid_left_side_landing": "a live step with ground_air_state 0 that m7g_fixture.classify_ground matches (tolerance "
                                   f"{fx.FLOOR_Y_TOL}) to a decoded left-side floor line {d['left_side_floor_lines']} "
                                   "and that is not the native-failure step",
        "left_target_break": "the exact replay's break table contains target 1, 6 or 8",
        "X": "1 iff >= 1 qualified-crossing episode or >= 1 verified left-target-break episode in the label",
        "recorded_never_required": ["btt_route_rule_v1 identity (lower_precision / upper_moving_platform / unclassified)",
                                    "right sweep complete at the entry", "entry class and y_c of unqualified entries",
                                    "landing surface of unqualified entries"],
        "geometry": {"left_boundary_x": d["left_boundary_x"], "wall_top_y": d["wall_top_y"], "ledge_x_span": d["ledge_x_span"],
                     "left_side_floor_lines": d["left_side_floor_lines"], "source_sha256": geometry().source_sha256},
        "reward_v3_constants": {"left_boundary_x": REWARD_V3.left_boundary_x, "wall_top_y": REWARD_V3.wall_top_y,
                                "entry_y_tolerance": REWARD_V3.entry_y_tolerance},
    }


# -- candidates --------------------------------------------------------------------------------------------------------


def candidate_reasons(e: Mapping[str, Any]) -> List[str]:
    em = e.get("eval_metrics") or {}
    r = []
    if em.get("first_left_entry") is not None:
        r.append("left_entry")
    if any(int(i) in LEFT_TARGET_IDS for i in em.get("broken_ids") or []):
        r.append("left_target")
    return r


def candidates(stochastic_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for e in sorted(stochastic_rows, key=lambda x: (x.get("order", 0), str(x.get("episode_id")))):
        reasons = candidate_reasons(e)
        if reasons:
            em = e.get("eval_metrics") or {}
            out.append({"episode_id": e.get("episode_id"), "native_action_digest": e.get("native_action_digest"),
                        "artifact_dir": e.get("artifact_dir"), "reasons": reasons, "end_reason": e.get("end_reason"),
                        "targets_broken": e.get("targets_broken"),
                        "recorded_breaks": [[int(b["target_id"]), int(b["consumed_tick"])] for b in em.get("target_breaks") or []],
                        "recorded_first_left_entry_tick": (em.get("first_left_entry") or {}).get("consumed_tick")
                        if em.get("first_left_entry") else None})
    return out


# -- trace analysis (pure) ---------------------------------------------------------------------------------------------


def _live(o: Mapping[str, Any]) -> bool:
    return int(o.get("fighter_valid", 0)) == 1 and int(o.get("btt_active", 0)) == 1


def analyse_trace(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]],
                  geo: Optional[fx.StageGeometry] = None) -> Dict[str, Any]:
    """Entries, exits, landings and the qualified-crossing verdict of one tick-0 stepping trace (raw replies)."""
    geo = geo or geometry()
    d = geo.derived
    xl = float(d["left_boundary_x"])
    left_floors = {f"L{i}" for i in d["left_side_floor_lines"]}
    ev = fx.crossing_evidence(geo, initial, steps)
    right = set(REWARD_V3.right_target_ids)
    breaks = [(int(b["target_id"]), int(b["consumed_tick"])) for b in ((ev.get("targets") or {}).get("breaks") or [])]
    io = initial.get("observation") or {}
    prev_live: Optional[Tuple[float, float]] = (float(io["position_x"]), float(io["position_y"])) if _live(io) else None
    region = "left" if prev_live is not None and prev_live[0] < xl else "right"
    entries: List[Dict[str, Any]] = []
    exits: List[Dict[str, Any]] = []
    landings: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    failure_step: Optional[int] = None
    for i, r in enumerate(steps):
        o = r.get("observation") or {}
        consumed = r.get("consumed_tick")
        fall = fx.is_fall(r)
        if fall and failure_step is None:
            failure_step = i
        if not _live(o):
            prev_live = None
            continue
        x, y = float(o["position_x"]), float(o["position_y"])
        if prev_live is not None:
            px, py = prev_live
            if px >= xl > x:
                cls, y_c = classify_entry(px, py, x, y, REWARD_V3)
                broken_so_far = {t for t, tick in breaks if tick <= int(consumed)}
                current = {"step_index": i, "consumed_tick": consumed, "class": cls, "y_c": round(y_c, 3), "x": x, "y": y,
                           "x_prev": px, "y_prev": py, "sweep_complete_at_entry": right <= broken_so_far,
                           "landing": None, "exit": None, "qualified": False}
                entries.append(current)
                region = "left"
            elif px < xl <= x:
                ex = {"step_index": i, "consumed_tick": consumed, "x": x, "y": y}
                exits.append(ex)
                if current is not None and current["exit"] is None:
                    current["exit"] = ex
                region = "right"
                current = None
        elif x < xl and region != "left":
            current = {"step_index": i, "consumed_tick": consumed, "class": UNPAIRED, "y_c": None, "x": x, "y": y,
                       "x_prev": None, "y_prev": None, "sweep_complete_at_entry": None, "landing": None, "exit": None,
                       "qualified": False}
            entries.append(current)
            region = "left"
        prev_live = (x, y)
        if int(o.get("ground_air_state", -1)) == 0 and region == "left" and x < xl:
            surface = fx.classify_ground(geo, o)
            land = {"step_index": i, "consumed_tick": consumed, "x": x, "y": y, "surface": surface,
                    "on_left_floor": surface in left_floors, "native_failure_step": fall}
            landings.append(land)
            if current is not None and current["landing"] is None and land["on_left_floor"] and not fall:
                current["landing"] = land
    takeoff_ok = ev.get("approach_surface") is not None
    over_ledge = ev.get("crossing_path") == "over_ledge"
    for en in entries:
        en["qualified"] = bool(en["class"] == OVER_WALL and over_ledge and takeoff_ok and en["landing"] is not None)
    route = fx.classify_crossing(ev, geo)
    left_breaks = [(t, tick) for t, tick in breaks if t in LEFT_TARGET_IDS]
    return {"criterion": CRITERION, "crossed": bool(ev.get("crossed")), "first_left_entry": ev.get("first_left_entry"),
            "crossing_path": ev.get("crossing_path"), "approach_surface": ev.get("approach_surface"),
            "route": route, "entries": entries, "exits": len(exits), "landings": landings,
            "qualified_crossing": any(e["qualified"] for e in entries),
            "first_qualified_entry": next((e for e in entries if e["qualified"]), None),
            "breaks": breaks, "left_target_breaks": left_breaks, "left_target_break": bool(left_breaks),
            "native_failure_step": failure_step, "terminal": ev.get("terminal"), "min_x": ev.get("min_x"),
            "wall_top": {k: ev["wall_top"][k] for k in ("steps_at_or_above_wall_top", "first_over_ledge")},
            "ground_unmatched_steps": ev.get("ground_unmatched_steps")}


# -- one candidate (game) ------------------------------------------------------------------------------------------


def replay_candidate(cand: Mapping[str, Any], work: Path, *, executable: Path, extra_env: Mapping[str, str],
                     index: int) -> Dict[str, Any]:
    import m7f_trace as tr
    from m7k_target2 import remove_runtime_with_retry

    art = Path(cand["artifact_dir"])
    art = art if art.is_absolute() else REPO_ROOT / art
    acts, _meta = tr.artifact_actions(art)
    t0 = time.perf_counter()
    trace = tr.run_stepping_trace(f"m7n_crossing_{index}", Path(executable), acts, Path(work), extra_env=dict(extra_env),
                                  index=index)
    steps = trace.get("steps") or []
    an = analyse_trace(trace["initial"], steps)
    recorded_breaks = [tuple(b) for b in cand.get("recorded_breaks") or []]
    replayed_first = (an["first_left_entry"] or {}).get("consumed_tick") if an["first_left_entry"] else None
    exact = {"consumed_tick_mismatch": trace.get("consumed_tick_mismatch"), "unsent": trace.get("unsent"),
             "digest_equal": trace.get("action_digest") == cand.get("native_action_digest"),
             "breaks_equal_recorded": [tuple(b) for b in an["breaks"]] == recorded_breaks,
             "first_left_entry_equal": replayed_first == cand.get("recorded_first_left_entry_tick"),
             "targets_equal": len(an["breaks"]) == int(cand.get("targets_broken") or 0)}
    exact["ok"] = bool(exact["consumed_tick_mismatch"] is None and exact["unsent"] == 0 and exact["digest_equal"]
                       and exact["breaks_equal_recorded"] and exact["first_left_entry_equal"] and exact["targets_equal"])
    cleanup = remove_runtime_with_retry(Path(work) / "runtime")
    return {"episode_id": cand["episode_id"], "native_action_digest": cand.get("native_action_digest"),
            "reasons": list(cand["reasons"]), "work": str(work), "actions": len(acts), "steps": len(steps),
            "exact": exact, "analysis": an,
            "qualified_crossing": bool(exact["ok"] and an["qualified_crossing"]),
            "verified_left_target_break": bool(exact["ok"] and an["left_target_break"]),
            "unqualified_left_entry": bool(exact["ok"] and an["crossed"] and not an["qualified_crossing"]),
            "runtime_cleanup": cleanup, "wall_s": round(time.perf_counter() - t0, 2)}


# -- one label -----------------------------------------------------------------------------------------------------


def read_stochastic(label_dir: Path) -> List[Dict[str, Any]]:
    f = Path(label_dir) / "stochastic" / "evaluation.json"
    if not f.is_file():
        raise FileNotFoundError(str(f))
    return list(json.loads(f.read_text(encoding="utf-8")).get("episodes") or [])


def verify_crossings_in(label_dir: Path, out_dir: Path, *, executable: Path, extra_env: Mapping[str, str],
                        index_base: int = REPLAY_INDEX_BASE) -> Dict[str, Any]:
    """Every gate-2 candidate of one final label replayed and analysed; the document is ALWAYS written (a label with
    zero candidates records X = 0 by the same criterion)."""
    label_dir, out_dir = Path(label_dir), Path(out_dir)
    cands = candidates(read_stochastic(label_dir))
    records = []
    for k, c in enumerate(cands):
        work = out_dir / f"crossing_{k:03d}_{str(c.get('native_action_digest'))[:8]}"
        if work.exists():
            raise FileExistsError(f"{work} exists (never overwritten)")
        records.append(replay_candidate(c, work, executable=executable, extra_env=extra_env, index=index_base + k))
    doc = summarise(label_dir, cands, records, executable=executable, extra_env=extra_env)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "crossing_verification.json").write_text(json.dumps(doc, indent=1, default=str) + "\n", encoding="utf-8")
    return doc


def summarise(label_dir: Path, cands: Sequence[Mapping[str, Any]], records: Sequence[Mapping[str, Any]], *,
              executable: Optional[Path], extra_env: Mapping[str, str]) -> Dict[str, Any]:
    import experiment_config as ec

    problems = [f"{r['episode_id']}: replay not exact {r['exact']}" for r in records if not r["exact"]["ok"]]
    q = sum(1 for r in records if r["qualified_crossing"])
    lt = sum(1 for r in records if r["verified_left_target_break"])
    return {"contract": CONTRACT, "criterion": CRITERION, "label_dir": ec.repo_relative(Path(label_dir)), "utc": utc_now(),
            "executable_sha256": sha256_file(Path(executable)) if executable else None, "flags": dict(extra_env),
            "geometry_source_sha256": geometry().source_sha256, "stochastic_episodes": len(read_stochastic(label_dir)),
            "candidates": len(cands), "candidate_digests": [c.get("native_action_digest") for c in cands],
            "exact": sum(1 for r in records if r["exact"]["ok"]),
            "qualified_crossings": q, "verified_left_target_episodes": lt,
            "unqualified_left_entries": sum(1 for r in records if r["unqualified_left_entry"]),
            "X": 1 if (q > 0 or lt > 0) and not problems else 0, "problems": problems, "ok": not problems,
            "records": list(records)}


# -- the rule's inputs (pure) ----------------------------------------------------------------------------------------


@dataclass
class CrossingInputs:
    candidates: int
    exact: int
    qualified_crossings: int
    verified_left_target_episodes: int
    unqualified_left_entries: int
    problems: List[str] = field(default_factory=list)

    @property
    def X(self) -> int:
        return 1 if (self.qualified_crossings > 0 or self.verified_left_target_episodes > 0) and not self.problems else 0

    def to_json(self) -> Dict[str, Any]:
        return dict(asdict(self), X=self.X)


def crossing_inputs(label_dir: Path, doc: Optional[Mapping[str, Any]]) -> Tuple[Optional[CrossingInputs], List[str]]:
    """The gate-2 inputs of a label from its verification document, cross-checked against the label's rows: the
    candidate set must be exactly the rows' candidates, every candidate exact. (None, [...]) when the document is
    missing (the driver treats that as pending); problems are integrity problems."""
    if doc is None:
        return None, [f"{Path(label_dir).name}: crossing verification missing"]
    p: List[str] = []
    want = [c.get("native_action_digest") for c in candidates(read_stochastic(label_dir))]
    if doc.get("contract") != CONTRACT or doc.get("criterion") != CRITERION:
        p.append(f"{Path(label_dir).name}: crossing document {doc.get('contract')} / {doc.get('criterion')}")
    if list(doc.get("candidate_digests") or []) != want:
        p.append(f"{Path(label_dir).name}: crossing candidates {doc.get('candidate_digests')} != rows {want}")
    recs = doc.get("records") or []
    if len(recs) != len(want):
        p.append(f"{Path(label_dir).name}: {len(recs)} crossing records for {len(want)} candidates")
    p.extend(str(x) for x in doc.get("problems") or [])
    ci = CrossingInputs(candidates=len(want), exact=sum(1 for r in recs if (r.get("exact") or {}).get("ok")),
                        qualified_crossings=sum(1 for r in recs if r.get("qualified_crossing")),
                        verified_left_target_episodes=sum(1 for r in recs if r.get("verified_left_target_break")),
                        unqualified_left_entries=sum(1 for r in recs if r.get("unqualified_left_entry")), problems=p)
    if ci.exact != ci.candidates and not p:
        p.append(f"{Path(label_dir).name}: {ci.exact}/{ci.candidates} candidates replayed exactly")
        ci.problems = p
    return ci, p


# -- self-test (synthetic traces, no game) ----------------------------------------------------------------------------


def _step(x: float, y: float, ga: int, tick: int, *, status: int = 1, state: int = 2, targets: int = 10) -> Dict[str, Any]:
    return {"consumed_tick": tick, "state": state, "observation": fx._obs(x, y, ga, tick=tick + 1, status=status,
                                                                            targets=targets)}


def _fly(points: Sequence[Tuple[float, float, int]], start: int = 0) -> List[Dict[str, Any]]:
    return [_step(x, y, g, start + i) for i, (x, y, g) in enumerate(points)]


def self_test() -> int:
    geo = geometry()
    fails: List[str] = []

    def expect(cond: bool, name: str, detail: Any = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {name}{'' if cond else ' ' + str(detail)}")
        if not cond:
            fails.append(name)

    initial = {"observation": fx._obs(0.0, -2550.0, 0, tick=0)}
    # A: the fixture-like lower crossing: grounded on L1, up over the ledge, left entry above the wall, landing on L3
    right_step = [(2200.0, -450.0, 0)] * 3
    up = [(1500.0, 1200.0, 1), (-800.0, 2400.0, 1), (-1500.0, 3100.0, 1), (-2050.0, 3300.0, 1)]
    over = [(-2150.0, 3200.0, 1), (-2600.0, 1000.0, 1), (-2800.0, -1200.0, 1)]
    land = [(-2800.0, -1950.0, 0)] * 5
    a = _fly(right_step + up + over + land)
    an = analyse_trace(initial, a, geo)
    expect(an["crossed"] and an["crossing_path"] == "over_ledge" and an["route"]["identity"] == "lower_precision",
           "A: crossing over the ledge from L1", an["route"])
    expect(len(an["entries"]) == 1 and an["entries"][0]["class"] == OVER_WALL and an["entries"][0]["landing"] is not None
           and an["entries"][0]["landing"]["surface"] == "L3" and an["qualified_crossing"], "A: qualified (landing on L3)",
           an["entries"])
    expect(an["entries"][0]["sweep_complete_at_entry"] is False, "A: sweep recorded as incomplete (never required)")
    # B: the M7h off-stage fall: left of -2100 under the stage, never grounded -> a left entry, not a crossing
    b = _fly([(-1000.0, -2550.0, 0), (-1900.0, -3200.0, 1), (-2150.0, -5000.0, 1), (-2300.0, -8412.0, 1)])
    b[-1]["observation"]["game_status"] = fx.GAME_STATUS_END
    bn = analyse_trace(initial, b, geo)
    expect(bn["crossed"] and bn["entries"][0]["class"] == "under_stage" and not bn["qualified_crossing"]
           and bn["native_failure_step"] == 3, "B: off-stage fall is a left entry, not qualified", bn["entries"])
    # C: over the wall, airborne only, then a fall (no landing) -> not qualified
    c = _fly(right_step + up + over + [(-2900.0, -4000.0, 1)])
    c[-1]["observation"]["game_status"] = fx.GAME_STATUS_END
    cn = analyse_trace(initial, c, geo)
    expect(cn["crossed"] and cn["entries"][0]["class"] == OVER_WALL and cn["entries"][0]["landing"] is None
           and not cn["qualified_crossing"], "C: over-wall entry without a landing is not qualified")
    # D: a landing on the native-failure step itself does not count
    dd = _fly(right_step + up + over + [(-2800.0, -1950.0, 0)])
    dd[-1]["observation"]["game_status"] = fx.GAME_STATUS_END
    dn = analyse_trace(initial, dd, geo)
    expect(not dn["qualified_crossing"] and dn["landings"] and dn["landings"][0]["native_failure_step"],
           "D: landing on the failure step is not a landing")
    # E: landing only after an exit and a second (unpaired-free) entry: the first visit is unqualified; the second
    # entry's landing qualifies that entry (same-visit rule)
    e_pts = right_step + up + over + [(-2050.0, 3100.0, 1), (-2150.0, 3200.0, 1), (-2700.0, 0.0, 1)] + land
    en = analyse_trace(initial, _fly(e_pts), geo)
    expect(len(en["entries"]) == 2 and en["entries"][0]["landing"] is None and en["entries"][1]["landing"] is not None
           and en["qualified_crossing"] and en["exits"] == 1, "E: landing belongs to its own visit", en["entries"])
    # F: grounded on an unmatched left position (not a decoded floor) is not a valid landing
    f = _fly(right_step + up + over + [(-2800.0, -1500.0, 0)] * 3)
    fn = analyse_trace(initial, f, geo)
    expect(not fn["qualified_crossing"] and fn["landings"][0]["surface"] == "ground_unmatched",
           "F: grounded off any decoded left floor is not a landing", fn["landings"][:1])
    # G: no left entry at all
    gn = analyse_trace(initial, _fly([(0.0, -2550.0, 0)] * 4), geo)
    expect(not gn["crossed"] and not gn["entries"] and not gn["qualified_crossing"] and gn["route"]["identity"] is None,
           "G: no entry")
    # H: candidates and inputs from rows
    rows = [{"order": 1, "episode_id": "e1", "native_action_digest": "d1", "eval_metrics": {"first_left_entry": None, "broken_ids": [0, 3]}},
            {"order": 0, "episode_id": "e0", "native_action_digest": "d0", "eval_metrics": {"first_left_entry": {"consumed_tick": 9}, "broken_ids": []}},
            {"order": 2, "episode_id": "e2", "native_action_digest": "d2", "eval_metrics": {"first_left_entry": None, "broken_ids": [6]}}]
    cs = candidates(rows)
    expect([c["episode_id"] for c in cs] == ["e0", "e2"] and cs[0]["reasons"] == ["left_entry"] and cs[1]["reasons"] == ["left_target"],
           "H: candidates in label order with reasons", cs)
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        lab = Path(td) / "final"
        (lab / "stochastic").mkdir(parents=True)
        (lab / "stochastic" / "evaluation.json").write_text(json.dumps({"episodes": rows}), encoding="utf-8")
        ci, p = crossing_inputs(lab, None)
        expect(ci is None and p, "H: missing document -> pending")
        rec_ok = {"episode_id": "e0", "exact": {"ok": True}, "qualified_crossing": True, "verified_left_target_break": False,
                  "unqualified_left_entry": False}
        rec_lt = {"episode_id": "e2", "exact": {"ok": True}, "qualified_crossing": False, "verified_left_target_break": True,
                  "unqualified_left_entry": False}
        doc = {"contract": CONTRACT, "criterion": CRITERION, "candidate_digests": ["d0", "d2"], "records": [rec_ok, rec_lt],
               "problems": []}
        ci, p = crossing_inputs(lab, doc)
        expect(ci is not None and not p and ci.X == 1 and ci.qualified_crossings == 1 and ci.verified_left_target_episodes == 1,
               "H: inputs from a complete document", (ci, p))
        bad = dict(doc, records=[dict(rec_ok, exact={"ok": False}, qualified_crossing=False), rec_lt])
        ci, p = crossing_inputs(lab, bad)
        expect(ci is not None and p and ci.X == 0, "H: an inexact candidate is an integrity problem and X is 0", p)
        ci, p = crossing_inputs(lab, dict(doc, candidate_digests=["d0"], records=[rec_ok]))
        expect(bool(p), "H: a candidate set that differs from the rows is a problem")
        empty = Path(td) / "empty"
        (empty / "stochastic").mkdir(parents=True)
        (empty / "stochastic" / "evaluation.json").write_text(json.dumps({"episodes": [rows[0]]}), encoding="utf-8")
        ci, p = crossing_inputs(empty, {"contract": CONTRACT, "criterion": CRITERION, "candidate_digests": [], "records": [], "problems": []})
        expect(ci is not None and not p and ci.candidates == 0 and ci.X == 0, "H: zero candidates -> X 0 by the same criterion")
    print(f"self-test: {'PASS' if not fails else 'FAIL ' + str(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["self-test"]:
        raise SystemExit(self_test())
    if sys.argv[1:] == ["criterion"]:
        print(json.dumps(criterion_description(), indent=1))
        raise SystemExit(0)
    print(__doc__)
    raise SystemExit(2)
