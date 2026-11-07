#!/usr/bin/env python3
"""Crossing search, run 3 (lab, exploratory, unregistered; 2026-11-06 session, step 8). The run 3 decisions are SESSION_LOG_2026-11-04.md
section 16 (MINOR table, DECISIVE 1-4b) and docs/rl_decisions_2026-11-04.md sections 4-5. Built on tools/frs/run3_search.py (run 2's engine
by import, the fused first dispatch, end records, D4, anomaly keeping, the run 3 code manifest); nothing inherited is edited.

    start           runs 1 + 2 merged (tools/frs/run3_load.py): the final representative of every cell with the same ids, both runs'
                    origins and dispatch statistics; the best VERIFIED clear of both runs (1,245 on the lab) sets the E7 bound through the
                    registered rule (1,220), fixed for the run; it is replayed once at the open, the import's reference too.
    selection       tools/frs/run3_select.py: 20 % breadth (count-based, anomaly triggers), otherwise level -> (level, mask, order niche)
                    group by its share (rate window warm-started from run 2, floor, demotion) -> anchors or the rank draw. Every
                    parameter is in Params3 and config.json. The start table (groups, shares, anchors, demotion) is computed at the plan
                    and again by the engine: they must be equal.
    records         dispatches.jsonl rows carry the stream, the group and the niche; cells.jsonl NEW / REPLACED rows carry `niche`,
                    `group` and, for a group move, `moved_from`; hourly.jsonl and hourly.md (each group's share, top 10, earliest arrival
                    per level, demotions and exits, fall rates, anchors, breadth, triggers) every summary_every_s of wall time (or every
                    summary_every_dispatches ingested dispatches, deterministic, for tests) and at the close; triggers.jsonl;
                    best_times.jsonl (every new verified best); exports.jsonl (a .btt.txt and a .bk2 for every verified clear, written when
                    it is verified); text_replays.jsonl (one native text replay per new verified best, at the close).
    plateau         the summary reads the Q11 plateau signals for this night: a faster verified clear, and the groups whose earliest
                    eligible arrival improved on the start (a new group counts).
    unchanged       claims replayed only when faster than the best, twice from tick 0 (verify flags); run 2's CONT arm (120 words, at most
                    6 segments, window 20); 5 workers + standby; caps; readiness; mismatch limit 3; lab digest recorded (not enforced),
                    run 3 digest enforced; identity unverified with the pinned executable.

    python -B tools/frs/crossing_search_run3.py plan --lab-root C:/BattleShip_lab --run1 DIR --run2 DIR [--out DIR] ...
    python -B tools/frs/crossing_search_run3.py run  --lab-root ... --run1 DIR --run2 DIR --out DIR [--workers 5] [--max-wall-min 480] ...

`plan` is zero native ticks; `run` is native. Writes only under the output folder through the lab's guard; the lab lock; nothing reads
native RNG. Zero-tick tests: tools/frs/crossing_search_run3_tests.py. Run with python -B.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping as _MappingABC
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (REPO / "rl", HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import crossing_search as cs  # noqa: E402
import crossing_search_run2 as r2  # noqa: E402
import det_schedule as det  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_report as frep  # noqa: E402
import frs_verify as fv  # noqa: E402
import m8_sd2_select as s6  # noqa: E402
import run3_anomaly as ra  # noqa: E402
import run3_export as rx  # noqa: E402
import run3_load as rl3  # noqa: E402
import run3_manifest as rm  # noqa: E402
import run3_search as r3  # noqa: E402
import run3_select as rs  # noqa: E402

RUN3_CONTRACT = "frs_crossing_search_run3_v1"
SearchError, Refused = cs.SearchError, cs.Refused
TRIGGER_CLASSES = ("line_crossing", "inside_solid", "floor_switch_unlinked", "nonfinite")
UNUSED_INHERITED = ("seeds", "seed_order", "novelty_exp", "seen_exp", "bonus_exp", "pace_exp", "check_queue_max", "eager_levels", "eager_max_min",
                    "canary_per_level", "check_error_limit")


# -- parameters ------------------------------------------------------------------------------------------------------------------------------


@dataclass
class Params3(r2.Params2):
    max_segments: int = 6               # run 2's CONT arm (MINOR table)
    reset_novelty: bool = True          # DECISIVE 1: counts carried from runs 1 + 2 reset (kept as information)
    breadth_share: float = 0.2          # DECISIVE 4
    window: int = 200                   # DECISIVE 1: the group's last 200 dispatches
    rank_exp: float = 1.0               # DECISIVE 1: (1 + rank)^-1
    novelty_floor: float = 0.05         # DECISIVE 1: max(0.05, 1 / (1 + dispatches since the representative was set))
    phi_factor: float = 0.25            # DECISIVE 1: phi = 1 / (4 x groups at the level)
    demote_min_dispatches: int = 1000   # DECISIVE 2
    demote_fall_rate: float = 0.75      # DECISIVE 2
    demote_share_factor: float = 0.25   # DECISIVE 2: a demoted group gets phi / 4
    anchor_k: int = 3                   # DECISIVE 3
    anchor_share: float = 0.5           # DECISIVE 3: 0.5 x w_max
    anchor_w_floor: float = 0.125       # DECISIVE 3
    trigger_classes: Tuple[str, ...] = TRIGGER_CLASSES   # DECISIVE 4
    trigger_rarity: int = 3             # DECISIVE 4: a class seen in fewer than 3 earlier bursts of the run
    trigger_draws_per_cell: int = 3     # DECISIVE 4
    trigger_cap: float = 0.1            # DECISIVE 4: trigger draws <= 10 % of breadth draws
    summary_every_s: float = 3600.0     # owner: hourly records
    summary_every_dispatches: int = 0   # tests: a record every k ingested dispatches instead (deterministic); 0 = by wall time

    def check(self) -> None:
        super().check()
        if not 0.0 <= self.breadth_share < 1.0 or not 0.0 < self.anchor_share <= 1.0 or not 0.0 < self.anchor_w_floor <= 1.0 or not 0.0 <= self.trigger_cap <= 1.0:
            raise SearchError("refused: --breadth-share in [0, 1), --anchor-share and --anchor-w-floor in (0, 1], --trigger-cap in [0, 1]")
        if self.window < 1 or self.anchor_k < 0 or self.trigger_rarity < 0 or self.trigger_draws_per_cell < 0 or self.demote_min_dispatches < 1:
            raise SearchError("refused: --window and --demote-min-dispatches are positive; --anchor-k, --trigger-rarity, --trigger-draws-per-cell are not negative")
        if not 0.0 < self.phi_factor <= 1.0 or not 0.0 < self.demote_share_factor <= 1.0 or not 0.0 <= self.demote_fall_rate <= 1.0 or self.rank_exp < 0 or not 0.0 <= self.novelty_floor <= 1.0:
            raise SearchError("refused: a selection parameter is out of range")
        if self.cleared_weight <= 0.0:
            raise SearchError("refused: run 3 keeps cleared starts eligible (--cleared-weight > 0)")
        if self.retire_after != 0:
            raise SearchError("refused: run 3 retires no cell (--retire-after 0)")
        if not self.reset_novelty:
            raise SearchError("refused: DECISIVE 1 resets the carried dispatch counts (reset_novelty)")
        if self.summary_every_s < 0 or self.summary_every_dispatches < 0 or (self.summary_every_s and self.summary_every_dispatches):
            raise SearchError("refused: hourly records by wall time OR by ingested dispatches, not both")

    def as_dict(self) -> Dict[str, Any]:
        d = super().as_dict()
        d.update({k: getattr(self, k) for k in ("breadth_share", "window", "rank_exp", "novelty_floor", "phi_factor", "demote_min_dispatches", "demote_fall_rate",
                                                "demote_share_factor", "anchor_k", "anchor_share", "anchor_w_floor", "trigger_rarity", "trigger_draws_per_cell",
                                                "trigger_cap", "summary_every_s", "summary_every_dispatches")})
        d["trigger_classes"] = list(self.trigger_classes)
        d["key_family"] = r3.KEY_FAMILY
        d["unused_inherited"] = list(UNUSED_INHERITED)
        return d


SELECTION_RULES = {
    "streams": "breadth with probability breadth_share (else exploitation); a breadth dispatch with no eligible cell outside demoted groups falls back to exploitation",
    "level": "decay level_decay^(deepest eligible level - level) over levels with an eligible cell (run 2's)",
    "group": "(level, mask, order niche) of the current representative (DECISIVE 4b)",
    "share": "rho = (window sum + 1) / (window length + 2), window = the last `window` dispatches worth u + e, warm start = `window` pseudo-dispatches at the "
             "whole-run-2 rate (u + e) / n (no history: the level's pooled rate); normalised over non-demoted groups, floored at phi = phi_factor / groups, "
             "rescaled to 1 - demoted x phi x demote_share_factor; a demoted group gets phi x demote_share_factor",
    "useful": "u = a break whose next-level arrival is <= the E7 bound; level 9: a claimed clear <= the bound (literal)",
    "e": "a kept cell at a deeper level earlier than every alive cell of its group before the burst; level 9: a claimed clear faster than every earlier claim",
    "demotion": "whole history (run 2 + run 3): n >= demote_min_dispatches, 0 bursts with any break, 0 e, falls >= demote_fall_rate x n; exit when it stops holding",
    "cell": "(1 + rank)^-rank_exp x max(novelty_floor, 1 / (1 + dispatches selected since the representative was set)) x cleared_weight^clears",
    "anchors": "the anchor_k earliest eligible cells per resource class per group; anchor draw with probability anchor_share x w_max: highest w, fewest anchor "
               "bursts (counted when selected), earliest tick, cell id; w = 1 on success (a kept deeper cell that is an anchor of its group; level 9: a claimed "
               "clear faster than every earlier claim), else halved, floor anchor_w_floor; a new or replaced anchor starts at w 1 and 0 bursts",
    "breadth": "weight 1 / (1 + dispatches of the cell id in runs 1-3, counted when selected) over the eligible cells of non-demoted groups, cell-id order",
    "triggers": "a burst with an event of trigger_classes seen in fewer than trigger_rarity earlier bursts queues, for a detector class, its kept eligible cells "
                "at ticks >= the event's step_from + 1; when there is none, and for a non-finite reply, the burst's last kept eligible cell, or the dispatched "
                "cell when it kept none (owner 2026-11-06); trigger_draws_per_cell breadth draws each, in turn; trigger draws <= trigger_cap x breadth draws",
    "moves": "a replacement into another niche: history and demotion stay with the group dispatched; staleness resets; the breadth count stays with the cell id; "
             "anchors recomputed in both groups",
}


# -- the plan (zero native ticks) ---------------------------------------------------------------------------------------------------------------


def read_best_source(d: Path, ref_t: int, archive_id: str) -> Dict[str, Any]:
    """A run 3 folder whose verified clears join the best and the bound (owner 2026-11-06, option c; its archive is NOT inherited): it
    must have stopped cleanly with a clean integrity record, on the same reference, archive id and margin. Read only."""
    d = Path(d)
    run = d / "run"
    for f in ("plan.json", "run/summary.json", "run/config.json"):
        if not (d / f).is_file():
            raise SearchError(f"refused: {d} is not a run 3 folder (missing {f})")
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    if summary.get("contract") != RUN3_CONTRACT or summary.get("mode") != "lab" or plan.get("contract") != RUN3_CONTRACT:
        raise SearchError(f"refused: {d} is not a {RUN3_CONTRACT} lab run")
    if summary.get("status") not in rl3.CLEAN_STATUSES:
        raise SearchError(f"refused: {d} did not stop cleanly (status {summary.get('status')})")
    integ = summary.get("integrity") or {}
    if integ.get("guard_violations_main") or integ.get("prefix_mismatches") or integ.get("battleship_left") or integ.get("reference_ok") is not True \
            or integ.get("run3_code_changed_during_run") or integ.get("run3_code_digest_end") != integ.get("run3_code_digest"):
        raise SearchError(f"refused: {d}'s integrity record is not clean: {integ}")
    if plan.get("archive_id") != archive_id or int(plan["e7"]["reference_completion_input_tick"]) != int(ref_t) or int(plan["e7"]["margin"]) != cs.MARGIN:
        raise SearchError(f"refused: {d} is not on the import's reference, archive id and margin")
    vp = run / "verifications.jsonl"
    ver = list(rl3.read_jsonl(vp)) if vp.is_file() else []
    tp = run / "text_replays.jsonl"
    text = {int(t["n"]): t for t in rl3.read_jsonl(tp) if t.get("n") is not None} if tp.is_file() else {}
    dp = run / "dispatches.jsonl"
    claims = [int(x["claimed"]["completion_input_tick"]) for x in rl3.read_jsonl(dp)
              if x.get("outcome") == "clear" and (x.get("claimed") or {}).get("completion_input_tick") is not None] if dp.is_file() else []
    ok = [v for v in ver if v.get("kind") == "clear" and v.get("verdict") == fv.VERIFIED]
    return {"dir": str(d), "status": summary.get("status"), "utc_start": summary.get("utc_start"), "utc_end": summary.get("utc_end"), "verifications": ver,
            "verified": len(ok), "best_in_folder": min((int(v["completion_input_tick"]) for v in ok), default=None), "text": text,
            "claims_min": min(claims) if claims else None, "verifications_sha256": g.sha256_file(vp) if vp.is_file() else None}


def build_plan(lab_root: Path, run1_dir: Path, run2_dir: Path, params: Params3, analyse: fv.Analyse = fv.real_analyse, *,
               code_digest: Optional[str] = None, best_from: Sequence[Path] = ()) -> Dict[str, Any]:
    params.check()
    R, meta = cs.read_reference(lab_root, analyse)
    R1 = r2.read_run1(run1_dir)
    p1 = R1["plan"]
    arrival = {int(k): int(v) for k, v in R["arrival"].items()}
    ref_t = int(R["expected"]["completion_input_tick"])
    if {str(k): v for k, v in arrival.items()} != {str(k): int(v) for k, v in p1["arrival_by_level"].items()}:
        raise SearchError("refused: run 1's arrival ticks per level are not the reference's")
    if p1["route"]["digest"] != R["meta"]["native_action_digest"] or p1.get("archive_id") != meta["archive_id"]:
        raise SearchError("refused: run 1's reference route or archive id is not the import's")
    if int(p1["e7"]["reference_completion_input_tick"]) != ref_t or int(p1["e7"]["margin"]) != cs.MARGIN:
        raise SearchError("refused: run 1's E7 block is not the registered reference and margin")
    v2 = list(rl3.read_jsonl(Path(run2_dir) / "run" / "verifications.jsonl")) if (Path(run2_dir) / "run" / "verifications.jsonl").is_file() else []
    extra = [read_best_source(Path(x), ref_t, meta["archive_id"]) for x in best_from]
    best = r2.best_verified_of(list(R1["verifications"]) + v2 + [v for X in extra for v in X["verifications"]], ref_t)

    def is_best(v: Mapping[str, Any]) -> bool:
        return int(v.get("n", -1)) == best["n"] and v.get("words_digest") == best["words_digest"]

    best["source"] = "run2" if any(is_best(v) for v in v2) else "run1"
    for X in extra:
        if any(is_best(v) for v in X["verifications"]):
            best["source"] = f"run3:{Path(X['dir']).name}"
            tr = X["text"].get(best["n"])
            if not tr or tr.get("equal") is not True:
                raise SearchError(f"refused: the best clear {best['completion_input_tick']} of {X['dir']} has no equal native text replay ({tr})")
    bound = s6.record_bound_max_L(best["completion_input_tick"], cs.MARGIN)
    D = rl3.load(Path(run1_dir), Path(run2_dir), bound, run1_rows=R1["rows"], run1_utc_start=R1["summary"].get("utc_start"))
    p2 = D["R2"]["plan"]
    if p2.get("archive_id") != meta["archive_id"] or p2["route"]["digest"] != R["meta"]["native_action_digest"] \
            or {str(k): int(v) for k, v in p2["arrival_by_level"].items()} != {str(k): v for k, v in arrival.items()} \
            or int(p2["e7"]["reference_completion_input_tick"]) != ref_t or int(p2["e7"]["margin"]) != cs.MARGIN:
        raise SearchError("refused: run 2's plan is not on the import's reference, archive id and margin")
    M, H = D["M"], D["history"]
    bound_check = int(p1["e7"]["bound_max_L"])
    if bound > int(p2["e7"]["bound_max_L"]):                  # the best of both runs is never slower than run 2's start
        raise SearchError(f"refused: run 3's bound {bound} is above run 2's {p2['e7']['bound_max_L']}")
    archive = r2.ResumeArchive(meta["archive_id"], arrival, bound, params)
    load = archive.load_run1({"final": M["final"], "origins": M["origins"], "dispatch_stats": M["dispatch_stats"]}, bound_check, M["cleared"],
                             reset_novelty=params.reset_novelty)
    best_claim = min(x for x in [M["best_claim"], int(best["completion_input_tick"])] + [X["claims_min"] for X in extra] if x is not None)
    sel = rs.Run3Selector(archive, params, niches=D["niches"], history=H["groups"], cid_dispatches=M["cid_dispatches"], best_claim=best_claim)
    digest = r2.archive_set_digest(M["final"], best, bound)
    code = code_digest if code_digest is not None else rm.code_digest(rm.run3_code_manifest())
    s1, s2 = R1["summary"], D["R2"]["summary"]
    run_block = lambda R_, s_, n_rows: {"dir": str(R_["dir"]), "contract": R_["plan"]["contract"], "utc_start": s_.get("utc_start"), "utc_end": s_.get("utc_end"),
                                         "status": s_.get("status"), "lab_code_digest": R_["config"].get("lab_code_digest"), "params": R_["plan"].get("params"),
                                         "cell_rows": n_rows, "dispatches": (s_.get("work") or {}).get("dispatches"), "clears_verified": (s_.get("clears") or {}).get("verified"),
                                         "e7_bound": int(R_["plan"]["e7"]["bound_max_L"])}
    run1_block = run_block(R1, s1, R1["rows"])
    run1_block["cells"] = len(R1["final"])
    plan = {"mode": "lab", "contract": RUN3_CONTRACT, "utc": g.utc(), "archive_id": meta["archive_id"], "key_family": r3.KEY_FAMILY,
            "rule": "crossing run 3: runs 1 + 2 merged with the same cell ids; E7 bound = the best VERIFIED clear of both runs minus the registered margin minus "
                    "one (fixed for the run); every inherited cell's first dispatch fused; selection by run3_select (DECISIVE 1-4b); claims replayed only when "
                    f"faster than the best; bursts from the key family {r3.KEY_FAMILY}",
            "run1": run1_block, "run2": run_block(D["R2"], s2, len(D["R2"]["rows"])),
            "route": {k: p1["route"][k] for k in ("words", "digest", "completion_input_tick", "completion_time_passed", "final_chain")},
            "arrival_by_level": {str(k): v for k, v in arrival.items()},
            "e7": {"reference_completion_input_tick": ref_t, "best_completion_input_tick": best["completion_input_tick"], "best_source": best["source"],
                   "run1_best_completion_input_tick": best["completion_input_tick"], "margin": cs.MARGIN, "bound_max_L": bound, "bound_run1": bound_check,
                   "bound_run2": int(p2["e7"]["bound_max_L"]), "best_from": [X["dir"] for X in extra],
                   "origin": "the registered rule (m8_sd1_select.record_bound_max_L) on the best VERIFIED clear of runs 1 + 2 and of the --best-from "
                             "run 3 folders (owner 2026-11-06, option c: their archives are not inherited)"},
            "best": {k: best[k] for k in ("n", "cid", "k", "level", "start_tick", "completion_input_tick", "completion_time_passed", "chain", "words_digest", "source")},
            "best_pace": {str(k): v for k, v in best["arrival"].items()}, "params": params.as_dict(), "arm": {cs.ARM_NAME: params.arm()}, "arm_base": cs.ARM_BASE,
            "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY,
            "archive": {"inherited": load["inherited"], "eligible": load["eligible"], "cleared_starts": load["cleared_starts"], "roots": load["roots"], "per_level": load["per_level"]},
            "eager": {"cells": 0, "levels_deep": [], "per_level": {}, "cids": [], "ticks": 0, "note": "run 3: no native check, every inherited cell's first dispatch is fused"},
            "check_fit": {}, "throughput_fit": {}, "archive_set_digest": digest, "seed_set_digest": digest, "seeds": 0, "seed_ticks": 0, "frontier": None,
            "run3": {"contract": RUN3_CONTRACT, "select_contract": rs.SELECT_CONTRACT, "start": sel.start, "rules": SELECTION_RULES, "code_digest": code,
                     "niche_stats": D["niche_stats"], "history": {"groups": H["groups"], "attribution": H["attribution"], "moves": H["moves"]},
                     "best_claim": best_claim, "claims": M["claims"], "groups": len(sel.start),
                     "best_from": [{k: X[k] for k in ("dir", "status", "utc_start", "utc_end", "verified", "best_in_folder", "claims_min",
                                                       "verifications_sha256")} for X in extra],
                     "anchors": sum(r["anchors"] for r in sel.start if r["eligible"]), "demoted": [r["group"] for r in sel.start if r["demoted"]]}}
    return {"plan": plan, "seeds": [], "R": R, "meta": meta, "bound": bound, "bound_run1": bound_check, "best": best, "R1": R1, "archive": archive,
            "cleared": M["cleared"], "run3_code_digest": code,
            "run3": {"niches": D["niches"], "history": H["groups"], "cid_dispatches": M["cid_dispatches"], "best_claim": best_claim}}


# -- the plan in a child process (2026-11-06: the run's footprint at the open) -------------------------------------------------------------------
#
# build_plan reads every row of both runs (181,657 cell rows, 70,008 dispatch rows) to derive the niches and run 2's history. In the run's
# main process that peaked at 1.53 GB of private bytes and left 1.34 GB committed at the open (CPython keeps the memory it freed), against
# 584 MB for run 2. `run` therefore builds the plan in a short-lived child process, which writes a compact payload: the plan, the reference
# record, the best clear, and one record per inherited cell holding exactly what ResumeArchive.load_run1 reads (its run 1 seed root
# included). The main process rebuilds the archive from it with load_run1 itself, then the engine compares its start table with the plan's.

PAYLOAD_CONTRACT = "run3_plan_payload_v1"


def plan_payload(P: Mapping[str, Any]) -> Dict[str, Any]:
    """The compact, picklable form of build_plan's result (child side)."""
    a = P["archive"]
    cells = [(c.cid, list(c.key), c.level, c.tick, c.lead, bytes(c.words), c.end_digest.hex(), c.chain.hex(), c.digest, dict(c.origin), c.seen,
              c.replaced, c.dispatched, c.breaks, c.cleared, c.root) for c in a.cells]
    R1 = P["R1"]
    return {"contract": PAYLOAD_CONTRACT, "plan": P["plan"], "R": P["R"], "meta": P["meta"], "bound": P["bound"], "bound_run1": P["bound_run1"],
            "best": P["best"], "R1": {"dir": str(R1["dir"]), "plan": R1["plan"], "config": R1["config"], "summary": R1["summary"], "rows": R1["rows"]},
            "archive_id": a.archive_id, "arrival": dict(a.arrival), "cells": cells, "cleared": P["cleared"], "run3": P["run3"],
            "run3_code_digest": P["run3_code_digest"]}


class _LazyFinal(_MappingABC):
    """The final representatives as load_run1 reads them, one row dict built per access (no 37,294 hex strings held at once)."""

    def __init__(self, cells: Sequence[Sequence[Any]]):
        self._cells = {int(t[0]): t for t in cells}

    def __getitem__(self, cid: int) -> Dict[str, Any]:
        (_cid, key, level, tick, lead, words, end_digest, chain, digest, origin, seen, replaced, *_rest) = self._cells[cid]
        return {"words_hex": words.hex(), "key": key, "level": level, "tick": tick, "lead": lead, "digest": digest, "end_digest": end_digest,
                "chain": chain, "origin": origin, "seen": seen, "replaced": replaced}

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._cells)

    def __len__(self) -> int:
        return len(self._cells)


def plan_from_payload(X: Mapping[str, Any], params: Params3) -> Dict[str, Any]:
    """build_plan's result rebuilt from a payload (main side): the archive is loaded by load_run1 itself from the same rows; each cell's
    lineage root comes from the payload (computed by load_run1 in the child from both runs' origins)."""
    if X.get("contract") != PAYLOAD_CONTRACT:
        raise SearchError(f"refused: a plan payload of contract {X.get('contract')!r}")
    archive = r2.ResumeArchive(X["archive_id"], {int(k): int(v) for k, v in X["arrival"].items()}, int(X["bound"]), params)
    cells = X["cells"]
    origins = {(int(t[0]), str(t[8])): {"kind": "seed", "fsid": t[15]} for t in cells}
    disp = {str(t[8]): [int(t[12]), int(t[13])] for t in cells}
    cleared = {int(t[0]): int(t[14]) for t in cells if t[14]}
    archive.load_run1({"final": _LazyFinal(cells), "origins": origins, "dispatch_stats": disp}, int(X["bound_run1"]), cleared,
                      reset_novelty=params.reset_novelty)
    bad = [int(t[0]) for t in cells if archive.cells[int(t[0])].root != t[15] or archive.cells[int(t[0])].digest != t[8]]
    if bad or len(archive.cells) != len(cells):
        raise SearchError(f"refused: the rebuilt archive differs from the plan's ({len(bad)} cells)")
    return {"plan": X["plan"], "seeds": [], "R": X["R"], "meta": X["meta"], "bound": int(X["bound"]), "bound_run1": int(X["bound_run1"]),
            "best": X["best"], "R1": X["R1"], "archive": archive, "cleared": X["cleared"], "run3": X["run3"], "run3_code_digest": X["run3_code_digest"]}


PLAN_CHILD = ("import json, sys\nsys.path.insert(0, %r); sys.path.insert(0, %r)\nimport frs_guard as g\nfrom pathlib import Path\n"
              "a = json.loads(sys.argv[1])\ng.LabGuard.install(Path(a['lab_root']))\nimport crossing_search_run3 as C\nC._plan_child(a)\n")


def _plan_child(a: Mapping[str, Any]) -> None:
    import pickle

    analyse = fv.real_analyse
    if a.get("analyse") == "stub":
        import m8_rd_stub as stub

        analyse = stub.analyse
    P = build_plan(Path(a["lab_root"]), Path(a["run1"]), Path(a["run2"]), Params3(**a["params"]), analyse, code_digest=a.get("code_digest"),
                   best_from=[Path(x) for x in a.get("best_from") or []])
    data = pickle.dumps(plan_payload(P), protocol=pickle.HIGHEST_PROTOCOL)
    with open(a["payload"], "wb") as f:
        f.write(data)


def plan_via_child(lab_root: Path, run1_dir: Path, run2_dir: Path, out: Path, params: Params3, *, code_digest: Optional[str],
                   analyse: str = "real", timeout: float = 900.0, best_from: Sequence[Path] = ()) -> Dict[str, Any]:
    """build_plan in a fresh child process (same code, same inputs), its payload read back and removed; the main process holds only
    what the run keeps."""
    import os
    import pickle
    import subprocess

    payload = Path(out) / "plan_payload.pkl"
    if payload.exists():
        raise SearchError(f"refused: {payload} exists (a previous plan child did not clean up)")
    pdict = {k: (list(v) if isinstance(v, tuple) else v) for k, v in params.__dict__.items()}
    args = {"lab_root": str(lab_root), "run1": str(run1_dir), "run2": str(run2_dir), "params": pdict, "code_digest": code_digest,
            "analyse": analyse, "payload": str(payload), "best_from": [str(x) for x in best_from]}
    code = PLAN_CHILD % (str(REPO / "rl"), str(HERE))
    r = subprocess.run([sys.executable, "-B", "-c", code, json.dumps(args)], capture_output=True, text=True, timeout=timeout, cwd=str(HERE))
    try:
        if r.returncode != 0 or not payload.is_file():
            raise SearchError(f"the plan child failed (exit {r.returncode}): {(r.stderr or r.stdout)[-1500:]}")
        with open(payload, "rb") as f:
            X = pickle.loads(f.read())
    finally:
        if payload.exists():
            os.remove(payload)
    if X.get("plan", {}).get("params") != params.as_dict():
        raise SearchError("refused: the plan child used other parameters")
    return plan_from_payload(X, params)


def plan_and_write(lab_root: Path, run1_dir: Path, run2_dir: Path, out: Path, params: Params3, analyse: fv.Analyse = fv.real_analyse, *,
                   code_digest: Optional[str] = None, best_from: Sequence[Path] = ()) -> Dict[str, Any]:
    P = build_plan(Path(lab_root), Path(run1_dir), Path(run2_dir), params, analyse, code_digest=code_digest, best_from=best_from)
    fs = g.LabFS(lab_root)
    saved = Path(out) / "plan.json"
    if saved.is_file():
        old = json.loads(saved.read_text(encoding="utf-8"))
        if old.get("archive_set_digest") != P["plan"]["archive_set_digest"]:
            raise SearchError(f"refused: {saved} exists with a different archive set ({str(old.get('archive_set_digest'))[:16]})")
    fs.mkdir(Path(out))
    fs.write_json(saved, P["plan"])
    return P


# -- the engine ---------------------------------------------------------------------------------------------------------------------------------


def burst_events(res: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The anomaly events of a burst as AnomalyIngest keeps them (glitch events without the audit samples, plus the non-finite one)."""
    glitch = res.get("glitch") or {}
    out = [dict(e) for e in glitch.get("events") or [] if not str(e.get("kind")).endswith("_sample")]
    nf = res.get("nonfinite")
    if nf and nf.get("event"):
        out.append(dict(nf["event"]))
    return out


class Run3Engine(r3.Run3Core):
    """Run 3's core with the step 7 selection (see the module docstring)."""

    def __init__(self, cfg: cs.SearchConfig, env: Any, P: Mapping[str, Any], params: Params3, *, text_replay: Optional[rx.TextReplayFn] = None):
        super().__init__(cfg, env, P, params)
        self.p3 = params
        X = P["run3"]
        self.selector = rs.Run3Selector(self.archive, params, niches=X["niches"], history=X["history"], cid_dispatches=X["cid_dispatches"],
                                        best_claim=X["best_claim"])
        diffs = rs.start_table_check(self.selector.start, self.plan["run3"]["start"])
        if diffs:
            raise SearchError(f"refused: the engine's start table is not the plan's: {diffs[:4]}")
        self.text_replay_fn = text_replay
        self.best_start = {k: v for k, v in self.best.items() if k != "words"}
        self._cur: Optional[Tuple[Mapping[str, Any], Mapping[str, Any]]] = None
        self._kept: List[Tuple[str, Any, rs.Niche]] = []
        self._row: Optional[Dict[str, Any]] = None
        self._post: List[List[int]] = []
        self.niche_live = rs.Counter()
        self._events_logged = 0
        self.hourly: List[Dict[str, Any]] = []
        self.hourly_md: List[str] = []
        self._next_record_t: Optional[float] = None
        self._final_record = False
        self.exports: List[Dict[str, Any]] = []
        self.text_replays: List[Dict[str, Any]] = []
        orig_keep = self.archive.keep

        def keep(key: Sequence[Any], level: int, tick: int, words: bytes, end: Sequence[Any], end_digest: bytes, chain: bytes, origin: Mapping[str, Any],
                 n_dispatch: int, **kw: Any) -> Tuple[str, Optional[cs.Cell]]:
            verdict, c = orig_keep(key, level, tick, words, end, end_digest, chain, origin, n_dispatch, **kw)
            if verdict in (cs.NEW, cs.REPLACED) and c is not None and self._cur is not None:
                info = self._cur[0]
                self._kept.append((verdict, c, rs.child_niche(info["niche"], int(c.key[3]), int(c.tick), self._post, self.niche_live)))
            return verdict, c

        self.archive.keep = keep  # an instance attribute: DeterministicSchedule wraps this one in turn

    # -- open -------------------------------------------------------------------------------------------------------------------------------

    def anchor_phase(self) -> None:
        """The best verified clear of runs 1 + 2 replayed once from tick 0 in a fresh process with the verify flags: it must reproduce exactly."""
        env, b = self.env, self.best
        words = bytes(b["words"])
        t = env.now()
        tr, errors = fv.replay_with_retry(env.replay, words, "best_start", 0)
        row = fv.evaluate(tr, words, env.analyse)
        fv.save_trace(self.dir / "traces" / "best_start.json.gz", tr)
        self.c["anchor_ticks"] += int(row.get("ticks") or 0)
        differs = [k for k, want in (("outcome", "clear"), ("completion_input_tick", b["completion_input_tick"]), ("completion_time_passed", b["completion_time_passed"]),
                                     ("final_chain", b["chain"]), ("action_digest", b["words_digest"]), ("breaks", b["breaks"]), ("ticks", len(words)))
                   if row.get(k) != want] + ([] if row.get("ticks_ok") else ["ticks_ok"])
        self.anchor = {"ok": not differs and row.get("outcome") == "clear", "differs": differs, "errors": errors, "completion_input_tick": row.get("completion_input_tick"),
                       "completion_time_passed": row.get("completion_time_passed"), "final_chain": row.get("final_chain"), "ticks": row.get("ticks"),
                       "startup_s": row.get("startup_s"), "stepping_s": row.get("stepping_s"), "wall_s": round(env.now() - t, 2), "source": b.get("source"),
                       "dispatch": b["n"], "cid": b["cid"], "k": b["k"], "words_digest": b["words_digest"]}
        self.fs.write_json(self.dir / "best_start.json", self.anchor)
        if not self.anchor["ok"]:
            if row.get("outcome") == "error":
                self.mark("SEARCH_INCOMPLETE", f"the best verified clear at the start could not be replayed: {errors[:2]}")
            else:
                self.mark("SEARCH_INVALID", f"the best verified clear at the start did not replay exactly: {differs}")
            return
        self.log(f"the best verified clear at the start ({b.get('source')}) replayed exactly: {row['completion_input_tick']} / {row['completion_time_passed']}; "
                 f"E7 bound {self.bound} = {b['completion_input_tick']} - {cs.MARGIN} - 1")

    # -- dispatch -----------------------------------------------------------------------------------------------------------------------------

    def next_job(self, w: int) -> Optional[Dict[str, Any]]:
        pick = self.selector.select(self.rng)
        if pick is None:
            self.mark("ARCHIVE_EMPTY", "no eligible cell is left to dispatch from")
            return None
        c, draw = pick
        job = self.build_job(w, c, draw)
        if job is not None:
            self.inflight[w].update(self.selector.on_dispatch(c, draw, self.c["dispatches"]))
        return job

    # -- ingest -------------------------------------------------------------------------------------------------------------------------------

    def handle(self, w: Any, kind: str, payload: Dict[str, Any]) -> None:
        info = self.inflight.get(w)
        super().handle(w, kind, payload)
        if info is not None and isinstance(payload, dict) and not payload.get("ok"):
            c = self.archive.cells[int(info["cid"])]
            if c.quarantined and c.cid in self.selector.group:
                self.selector.on_quarantine(c)

    def commit(self, info: Mapping[str, Any], c: cs.Cell, res: Mapping[str, Any]) -> None:
        L = int(res["L"])
        self._post = [[int(t), int(i)] for t, i in (res.get("breaks_all") or []) if int(t) > L]
        sm, order = info["niche"]
        if (int(sm) & ~sum(1 << int(t) for t in order)) != int(c.key[3]) and c.digest == info["digest"]:
            self.niche_live["parent_mask_mismatch"] += 1
        self._cur, self._kept, self._row = (info, res), [], None
        try:
            super().commit(info, c, res)
        finally:
            self._cur = None
        row = self._row or {}
        out = self.selector.on_ingest(info, row, self._kept, burst_events(res), int(info["n"]))
        if out["trigger"] is not None:
            t = self.selector.triggers[out["trigger"]]
            self.fs.append_jsonl(self.dir / "triggers.jsonl", dict(t, utc=g.utc()))
            self.event(f"anomaly trigger {t['index']}: dispatch {t['n']} classes {t['classes']}, {len(t['cells'])} kept cells queued for "
                       f"{t['draws_queued']} breadth draws")
        for ev in self.selector.events[self._events_logged:]:
            self.event(f"group {ev['group']} {ev['kind']} at dispatch {ev['n']}: {ev['history']}")
        self._events_logged = len(self.selector.events)
        self._kept = []
        k = self.p3.summary_every_dispatches
        if k and self.selector.n_ingested % k == 0:
            self.write_record("dispatches")

    def emit(self, row: Dict[str, Any]) -> None:
        if self._cur is not None and row.get("kind", "burst") == "burst" and row.get("n") == self._cur[0]["n"]:
            info = self._cur[0]
            row["stream"] = info["stream"]
            row["group"] = rs.glabel(info["group"])
            row["niche"] = rs.niche_label(info["niche"])
            self._row = row
        super().emit(row)

    def emit_cell(self, verdict: str, c: cs.Cell, info: Optional[Mapping[str, Any]], previous: Optional[Mapping[str, Any]] = None) -> None:
        row = {"ev": verdict, "cid": c.cid, "key": list(c.key), "level": c.level, "tick": c.tick, "lead": c.lead, "slack": self.archive.slack_of(c.tick), "digest": c.digest,
               "end_digest": c.end_digest.hex(), "chain": c.chain.hex(), "origin": c.origin, "n": self.c["dispatches"], "seen": c.seen, "replaced": c.replaced,
               "first_at_level": c.first_level_reach if verdict == cs.NEW else False, "utc": g.utc(), "words_hex": c.words.hex() if c.words is not None else None,
               "end": list(c.end) if c.verified and c.end else None}
        if self._kept and self._kept[-1][1] is c:
            niche = self._kept[-1][2]
            row["niche"] = rs.niche_label(niche)
            row["group"] = rs.glabel(self.selector.gkey_of(c, niche))
            old = self.selector.group.get(c.cid)
            if old is not None and rs.glabel(old) != row["group"]:
                row["moved_from"] = rs.glabel(old)
        if previous:
            row["previous"] = dict(previous)
        with self._lock:
            self.fs.append_jsonl(self.dir / "cells.jsonl", row)

    # -- verified clears: best times and exports ------------------------------------------------------------------------------------------------

    def on_verified(self, cand: Mapping[str, Any], out: Mapping[str, Any]) -> None:
        prev = self.best["completion_input_tick"]
        super().on_verified(cand, out)
        row = self.vrows[-1]
        if row["verdict"] != fv.VERIFIED:
            return
        words = bytes.fromhex(row["words_hex"])
        try:
            ex = rx.export_clear(self.fs, self.dir / "clears", f"clear_n{row['n']}_t{row['completion_input_tick']}", words,
                                 {"n": row["n"], "cid": row["cid"], "k": row["k"], "completion_input_tick": row["completion_input_tick"],
                                  "completion_time_passed": row["completion_time_passed"], "words_digest": row["words_digest"], "run": "run3"})
        except Exception as exc:  # noqa: BLE001 - recorded; the clear stays verified
            ex = {"name": f"clear_n{row['n']}", "error": f"{type(exc).__name__}: {exc}"[:300]}
        ex.update({"n": row["n"], "completion_input_tick": row["completion_input_tick"], "utc": g.utc()})
        self.exports.append(ex)
        self.fs.append_jsonl(self.dir / "exports.jsonl", ex)
        if ex.get("roundtrip_ok") is False or ex.get("error"):
            self.event(f"the export of verified clear {row['n']} failed: {ex.get('error') or 'bk2 round trip'}")
        if int(self.best["completion_input_tick"]) < int(prev) and int(self.best["n"]) == int(row["n"]):
            bt = {"completion_input_tick": row["completion_input_tick"], "completion_time_passed": row["completion_time_passed"], "previous_best": prev,
                  "gain": int(prev) - int(row["completion_input_tick"]), "n": row["n"], "cid": row["cid"], "k": row["k"], "words_digest": row["words_digest"],
                  "chain_r1": row["chain_r1"], "chain_r2": row["chain_r2"], "verdict": row["verdict"], "btti": ex.get("btti"), "bk2": ex.get("bk2"), "utc": g.utc()}
            self.fs.append_jsonl(self.dir / "best_times.jsonl", bt)

    def close_verifications(self) -> None:
        super().close_verifications()
        self.run_text_replays()

    def run_text_replays(self) -> None:
        """One native text replay per new verified best of this run, when no other game process runs (MINOR O7)."""
        news = [b for b in self.best_history]
        if not news:
            return
        if self.text_replay_fn is None:
            self.text_replays = [{"n": b["n"], "skipped": "no text replay configured"} for b in news]
            return
        left = self.env.wait_no_battleship(60.0)
        by_n = {int(v["n"]): v for v in self.vrows if v["verdict"] == fv.VERIFIED}
        for b in news:
            v = by_n.get(int(b["n"]))
            if v is None:
                continue
            if left:
                rec = {"n": b["n"], "skipped": f"game processes still running: {left}"}
            else:
                try:
                    rep = self.text_replay_fn(bytes.fromhex(v["words_hex"]), f"best_n{v['n']}_t{v['completion_input_tick']}")
                except Exception as exc:  # noqa: BLE001 - a text replay that cannot run is recorded, never raised into the close
                    rep = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
                rec = dict(rx.text_replay_verdict(rep, int(v["completion_input_tick"]), int(v["completion_time_passed"])), n=v["n"], btti_sha256=rep.get("btti_sha256"))
                if rep.get("ok") and not rec["equal"]:
                    self.mark("SEARCH_INVALID", f"verified best {v['n']} ({v['completion_input_tick']}): the native text replay gave {rec['clocks_text']}")
            rec["utc"] = g.utc()
            self.text_replays.append(rec)
            self.fs.append_jsonl(self.dir / "text_replays.jsonl", rec)

    # -- hourly records ---------------------------------------------------------------------------------------------------------------------------

    def progress(self, force: bool = False) -> None:
        super().progress(force)
        p = self.p3
        if p.summary_every_s and not p.summary_every_dispatches and self.phase == "search":
            now = self.env.now()
            if self._next_record_t is None:
                self._next_record_t = self.t_search + p.summary_every_s
            elif now >= self._next_record_t:
                self._next_record_t += p.summary_every_s
                self.write_record("wall")

    def write_record(self, at: str) -> Dict[str, Any]:
        verified = [v for v in self.vrows if v["verdict"] == fv.VERIFIED]
        meta = {"at": at, "index": len(self.hourly), "utc": g.utc(), "elapsed_s": round(self.elapsed(), 1) if at != "dispatches" else None,
                "dispatches": self.c["dispatches"] if at != "dispatches" else None, "best_verified": int(self.best["completion_input_tick"]),
                "best_start": int(self.best_start["completion_input_tick"]), "claims": self.c["clears_claimed"], "verified": len(verified),
                "status": self.status}
        rec = self.selector.snapshot(meta)
        self.hourly.append({k: rec[k] for k in ("at", "index", "ingested_total")})
        self.fs.append_jsonl(self.dir / "hourly.jsonl", rec)
        self.hourly_md.append(hourly_md(rec))
        try:
            self.fs.write_text(self.dir / "hourly.md", "# Run 3: hourly records\n\n" + "\n".join(reversed(self.hourly_md)), atomic=True)
        except (OSError, g.LabRootError):
            pass
        return rec

    # -- records ----------------------------------------------------------------------------------------------------------------------------------

    def plateau(self) -> Dict[str, Any]:
        start = {r["group"]: r["earliest_eligible"] for r in self.plan["run3"]["start"] if r["eligible"]}
        now = {r["group"]: r["earliest_eligible"] for r in self.selector.table() if r["eligible"]}
        improved = {gl: [start.get(gl), t] for gl, t in sorted(now.items()) if t is not None and (start.get(gl) is None or t < start[gl])}
        faster = int(self.best["completion_input_tick"]) < int(self.best_start["completion_input_tick"])
        return {"rule": "Q11: read on verified clears and on the earliest arrival per group; three nights without progress end the line",
                "faster_verified_clear": faster, "best_start": int(self.best_start["completion_input_tick"]), "best_end": int(self.best["completion_input_tick"]),
                "groups_earliest_improved": improved, "progress": bool(faster or improved)}

    def config_record(self, ready: Mapping[str, Any]) -> Dict[str, Any]:
        rec = super().config_record(ready)
        rec["contract"] = RUN3_CONTRACT
        rec["run3_file_sha256"] = {Path(m.__file__).name: g.sha256_file(Path(m.__file__).resolve()) for m in (sys.modules[__name__], rs, rl3, rx)}
        rec["run2"] = self.plan["run2"]
        rec["best_start"] = self.plan["best"]
        rec["run3"]["selection"] = {"contract": rs.SELECT_CONTRACT, "params": self.p3.as_dict(), "rules": SELECTION_RULES, "start": self.plan["run3"]["start"],
                                    "demoted_at_start": self.plan["run3"]["demoted"], "anchors_at_start": self.plan["run3"]["anchors"],
                                    "history": self.plan["run3"]["history"], "niche_stats": self.plan["run3"]["niche_stats"], "det_lag": getattr(self, "det_lag", None)}
        rec["origins"]["selection"] = "tools/frs/run3_select.py (DECISIVE 1-4b; SESSION_LOG_2026-11-04.md section 16)"
        rec["origins"]["archive"] = "runs 1 + 2 cells.jsonl merged: the last row per cell id (tools/frs/run3_load.py)"
        rec["origins"]["e7"] = "the registered rule on the best VERIFIED clear of runs 1 + 2 and the registered margin; fixed for the run"
        return rec

    def summary(self) -> Dict[str, Any]:
        s = super().summary()
        s["contract"] = RUN3_CONTRACT
        verified = self.verified_clears()
        s["run3"].update({"best": {k: v for k, v in self.best.items() if k != "words"}, "best_start": self.best_start, "best_history": list(self.best_history),
                          "faster_than_start": sum(1 for v in verified if int(v["completion_input_tick"]) < int(self.best_start["completion_input_tick"])),
                          "selection": self.selector.summary(), "start": self.plan["run3"]["start"], "plateau": self.plateau(), "niche_live": dict(self.niche_live),
                          "exports": list(self.exports), "text_replays": list(self.text_replays), "hourly_records": list(self.hourly)})
        return s

    def write_summary(self) -> Dict[str, Any]:
        if not self._final_record and self.selector.n_ingested:
            self._final_record = True
            try:
                self.write_record("close")
            except Exception as exc:  # noqa: BLE001 - a record, never the close
                self.log(f"the closing record failed: {type(exc).__name__}: {exc}"[:300])
        if self.run3_code and "run3_code_digest_end" not in self.integrity:
            end = rm.code_digest(rm.run3_code_manifest())
            changed = rm.changed_files(self.run3_code)
            self.integrity.update({"run3_code_digest": self.run3_code_dig, "run3_code_digest_end": end, "run3_code_changed_during_run": changed})
            if end != self.run3_code_dig or changed:
                self.mark("SEARCH_INVALID", f"the run 3 code changed during the run: {changed[:6] or 'the imported set changed'}")
        if self.sampler is not None:
            self.sampler.stop()
        s = self.summary()
        self.fs.write_text(self.dir / "summary.json", frep.compact_json(s), atomic=True)
        self.fs.write_text(self.dir / "report.md", report_md3(s), atomic=True)
        self.fs.write_text(self.dir / "progress.md", progress_md3(s, final=True), atomic=True)
        return s

    def write_progress(self) -> None:
        try:
            self.fs.write_text(self.dir / "progress.md", progress_md3(self.summary(), final=False), atomic=True)
        except (OSError, g.LabRootError):
            pass


class Run3Night(det.DeterministicSchedule, ra.AnomalyIngest, Run3Engine):
    """Run 3: deterministic scheduling (D4), anomaly keeping, fused first dispatches, the step 7 selection."""


# -- rendering --------------------------------------------------------------------------------------------------------------------------------------


def _f(x: Any) -> str:
    return frep.fmt(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else ("-" if x is None else str(x))


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{100.0 * x:.1f} %"


def gmd(label: str) -> str:
    """A group label for a markdown table cell: (level, mask, niche) without the '|' that would split the cell."""
    return "(" + ", ".join(str(label).split("|", 2)) + ")"


def group_table_md(groups: Sequence[Mapping[str, Any]], *, period: bool) -> List[str]:
    head = "| group (level, mask, niche) | eligible | share | rho | demoted | falls run 3 / whole | b / useful / e (run 3) | anchors |"
    sep = "| --- | ---: | ---: | ---: | --- | --- | --- | --- |"
    if period:
        head = ("| group (level, mask, niche) | eligible | share | rho | demoted | dispatches: rank / anchor / breadth / trigger | top-10 share: dispatches / "
                "weight | falls run 3 / whole | b / useful / e (run 3) | anchors: n, bursts, successes, w |")
        sep = "| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |"
    out = [head, sep]
    for r in groups:
        h3, hw = r["run3"], r["history"]
        fr3 = _pct(h3["fall"] / h3["n"]) if h3["n"] else "-"
        cells = [gmd(r["group"]), _f(r["eligible"]), _pct(r["share"]), f"{r['rho']:.4f}" if r["rho"] is not None else "-", "**yes**" if r["demoted"] else "no"]
        if period:
            pd_ = r.get("period") or {}
            cells.append(f"{pd_.get('dispatches', 0)}: {pd_.get('rank', 0)} / {pd_.get('anchor', 0)} / {pd_.get('breadth', 0)} / {pd_.get('trigger', 0)}")
            cells.append(f"{_pct(r.get('top10_share_dispatches'))} / {_pct(r.get('top10_weight_share'))}")
        cells.append(f"{fr3} ({h3['n']}) / {_pct(r['fall_rate'])} ({hw['n']})")
        cells.append(f"{h3['b']} / {h3['bu']} / {h3['e']}")
        if period:
            ad = r.get("anchors_detail") or []
            ws = [a["w"] for a in ad]
            cells.append(f"{r['anchors']}, {r.get('anchor_bursts_ingested', 0)}, {r.get('anchor_successes', 0)}, "
                         + (f"{min(ws):.3g}-{max(ws):.3g}" if ws else "-"))
        else:
            cells.append(str(r["anchors"]))
        out.append("| " + " | ".join(cells) + " |")
    return out


def hourly_md(rec: Mapping[str, Any]) -> str:
    per, br, tr = rec["period"], rec["breadth"], rec["triggers"]
    title = {"wall": "Hourly record", "dispatches": "Record", "close": "Closing record"}.get(rec["at"], "Record")
    L = [f"## {title} {rec['index']}: {rec['utc']} (ingested {_f(rec['ingested_total'])}"
         + (f", dispatched {_f(rec['dispatches'])}, {rec['elapsed_s'] / 3600.0:.2f} h" if rec.get("elapsed_s") is not None else "") + ")", ""]
    L.append(f"- Best verified **{_f(rec['best_verified'])}** (start {_f(rec['best_start'])}); claims {_f(rec['claims'])}, verified {_f(rec['verified'])}; "
             f"fastest claim {_f(rec.get('best_claim'))}.")
    L.append("- Earliest arrival per level: " + " · ".join(f"L{lv} **{_f(d['tick'])}** ({d['group']}, cell {d['cid']})" for lv, d in rec["earliest_by_level"].items()
                                                         if int(lv) >= 6) + ".")
    st = per["streams"]
    L.append(f"- This period: {_f(per['dispatches'])} dispatched, {_f(per['ingested'])} ingested; streams rank {st.get('rank', 0)}, anchor {st.get('anchor', 0)}, "
             f"breadth {st.get('breadth', 0)}, trigger {st.get('trigger', 0)} (breadth fallbacks {per['fallback_exploit']}); useful breaks "
             f"{json.dumps(per['useful'])}; new earliest arrivals {json.dumps(per['e'])}; group moves {per['moves']} (total {_f(rec['moves_total'])}).")
    L += ["", "### Groups", ""] + group_table_md(rec["groups"], period=True)
    L += ["", "### Demotions and exits", ""]
    if rec["demotions"]:
        for ev in rec["demotions"]:
            L.append(f"- **{ev['kind']}** {ev['group']} at dispatch {ev['n']}: history {json.dumps(ev['history'])} (fall rate {_pct(ev['fall_rate'])}), run 3 "
                     f"{json.dumps(ev['run3'])}")
    else:
        L.append("- none this period.")
    L += ["", "### Anchors", ""]
    for r in rec["groups"]:
        ad = r.get("anchors_detail") or []
        if ad:
            L.append(f"- {r['group']}: " + "; ".join(f"{a['class']} c{a['cid']} @{a['tick']} w {a['w']:.3g} b {a['bursts']} s {a['successes']}" for a in ad))
    L += ["", "### Breadth", "",
          f"- Draws by level {json.dumps(br['by_level'])}; pool {_f(br['pool'])} eligible cells outside demoted groups, {_f(br['never_dispatched'])} never dispatched.",
          f"- Useful breaks: breadth {br['useful_breadth']} against exploitation {br['useful_exploitation']}; new earliest arrivals breadth {br['e_breadth']} "
          f"against {br['e_exploitation']}.",
          "- By group: " + (", ".join(f"{k} {v}" for k, v in sorted(br["by_group"].items(), key=lambda kv: -kv[1])[:12]) or "-") + ".",
          "- By niche: " + (", ".join(f"{k} {v}" for k, v in sorted(br["by_niche"].items(), key=lambda kv: -kv[1])[:12]) or "-") + "."]
    L += ["", "### Anomaly triggers", "",
          f"- Trigger draws {tr['trigger_draws']} of {tr['breadth_draws']} breadth draws (cap: {tr['allowed_now']} allowed now); queue {tr['queue']}; dropped "
          f"this period {tr['dropped']}; classes seen {json.dumps(tr['classes_seen'])}; triggers in the run {tr['total']}."]
    for t in tr["new"]:
        L.append(f"- Trigger {t['index']}: dispatch {t['n']}, classes {t['classes']}, {len(t['cells'])} cells from tick {t['first_tick']}, "
                 f"{t['draws_queued']} draws queued, {t['draws_given']} given.")
    return "\n".join(L) + "\n"


def _status_lines(s: Mapping[str, Any]) -> List[str]:
    r3s = s["run3"]
    b, b0 = r3s["best"], r3s["best_start"]
    gain = int(b0["completion_input_tick"]) - int(b["completion_input_tick"])
    L = [f"Status **{s['status']}** ({(s.get('stop') or {}).get('reason')}); dispatches {_f(s['work']['dispatches'])}, jobs {_f(s['work']['jobs'])}, "
         f"ticks {_f(s['work']['ticks_total'])}.", "",
         f"Best verified clear: **{_f(b['completion_input_tick'])} / {_f(b.get('completion_time_passed'))}** "
         + (f"(run 3, dispatch {b['n']}, cell {b['cid']}): FASTER than the start's {_f(b0['completion_input_tick'])} by {gain} ticks." if gain > 0
            else f"(the start's, {b0.get('source')}): no faster clear verified in this run."), ""]
    cl = (s.get("run2") or {}).get("claims") or {}
    L.append(f"Claims: {_f(cl.get('claimed'))} claimed, {_f(cl.get('replayed'))} replayed (faster than the best), {_f(cl.get('not_replayed'))} not replayed.")
    return L


def _selection_lines(s: Mapping[str, Any]) -> List[str]:
    sel = s["run3"]["selection"]
    L = ["## Selection", "", f"Streams {json.dumps(sel['streams'])}; useful breaks {json.dumps(sel['useful'])}; new earliest arrivals {json.dumps(sel['e'])}; "
                             f"group moves {sel['counters'].get('moves', 0)}; breadth fallbacks {sel['counters'].get('fallback_exploit', 0)}.", ""]
    L += group_table_md(sel["table"], period=False)
    ev = sel["events"]
    L += ["", f"Demotions and exits in the run: {len(ev)}" + ("" if not ev else ": " + "; ".join(f"{e['kind']} {e['group']} at {e['n']}" for e in ev[:20])) + "."]
    L += [f"Anomaly triggers: {len(sel['triggers'])} (queue {sel['trigger_queue']}); classes seen {json.dumps(sel['classes_seen'])}."]
    pl = s["run3"]["plateau"]
    L += ["", "## Plateau reading (Q11)", "", f"- Faster verified clear this night: **{pl['faster_verified_clear']}** ({pl['best_start']} -> {pl['best_end']}).",
          f"- Groups whose earliest eligible arrival improved on the start: {len(pl['groups_earliest_improved'])}"
          + ("" if not pl["groups_earliest_improved"] else ": " + "; ".join(f"{k} {v[0]} -> {v[1]}" for k, v in list(pl["groups_earliest_improved"].items())[:12])) + ".",
          f"- Progress this night: **{pl['progress']}**."]
    return L


def _records_lines(s: Mapping[str, Any]) -> List[str]:
    r3s = s["run3"]
    e = r3s["end_records"]
    L = ["## Records", "", f"- End records: fused {e['fused']} (ok {e['fused_ok']}, mismatch {e['fused_mismatch']}, repeat {e['fused_repeat']}, stale {e['fused_stale']}), "
                           f"stored {e['end_records']}; eligible without one {_f(e['eligible_without_end_record'])}.",
         f"- Exports (.btt.txt + .bk2 per verified clear): {len(r3s['exports'])}" + ("" if not r3s["exports"] else
                                                                                  f", round trips ok {sum(1 for x in r3s['exports'] if x.get('roundtrip_ok'))}") + ".",
         f"- Native text replays of new bests: {len(r3s['text_replays'])}" + ("" if not r3s["text_replays"] else ": " + "; ".join(
             f"n {t.get('n')} {'equal' if t.get('equal') else (t.get('skipped') or t.get('error') or t.get('clocks_text'))}" for t in r3s["text_replays"])) + ".",
         f"- Hourly records: {len(r3s['hourly_records'])} (hourly.md, hourly.jsonl).",
         f"- Anomalies: {json.dumps({k: v for k, v in (s.get('anomalies') or {}).items() if k in ('events', 'bursts', 'nonfinite', 'scan_errors', 'by_kind')})}.",
         f"- Integrity: {json.dumps({k: v for k, v in (s.get('integrity') or {}).items() if k != 'run3_code_changed_during_run'}, default=str)[:900]}."]
    return L


def progress_md3(s: Mapping[str, Any], *, final: bool) -> str:
    L = [f"# Crossing search run 3: progress ({s.get('utc_end')})", "", "Final." if final else "Running.", ""] + _status_lines(s)
    eb = s["run3"]["selection"]["earliest_by_level"]
    L += ["", "## Earliest arrival per level", "", " · ".join(f"L{lv} {_f(d['tick'])} ({d['group']})" for lv, d in eb.items() if int(lv) >= 6) + "."]
    L += [""] + _selection_lines(s) + [""] + _records_lines(s)
    return "\n".join(L) + "\n"


def report_md3(s: Mapping[str, Any]) -> str:
    L = [f"# Crossing search run 3 ({s.get('utc_start')} - {s.get('utc_end')})", "", "THE RULES: SESSION_LOG_2026-11-04.md section 16; config.json holds every parameter.", ""]
    L += _status_lines(s) + [""] + _selection_lines(s) + [""] + _records_lines(s)
    L += ["", "## Verified clears", ""]
    for v in s["clears"]["rows"]:
        L.append(f"- dispatch {v['n']} cell {v['cid']} k {v['k']}: {v['verdict']} {v['completion_input_tick']} / {v['completion_time_passed']} (chains equal "
                 f"{v['chain_r1'] == v['chain_r2']})")
    return "\n".join(L) + "\n"


# -- command line ---------------------------------------------------------------------------------------------------------------------------------


def params_from_args(a: argparse.Namespace) -> Params3:
    p = Params3(level_decay=a.level_decay, max_segments=a.max_segments, max_cells=a.max_cells, max_dispatches=a.max_dispatches, rng_seed=a.rng_seed,
                cleared_weight=a.cleared_weight, check_slots=a.check_slots, breadth_share=a.breadth_share, summary_every_s=a.summary_every_s,
                summary_every_dispatches=a.summary_every_dispatches)
    p.check()
    return p


def run_command(lab_root: Path, run1: Path, run2: Path, out: Path, a: argparse.Namespace) -> str:
    return (f"python -B tools/frs/crossing_search_run3.py run --lab-root {Path(lab_root).as_posix()} --run1 {Path(run1).as_posix()} --run2 {Path(run2).as_posix()} "
            f"--out {Path(out).as_posix()} --workers {a.workers} --max-ticks {a.max_ticks} --max-wall-min {a.max_wall_min:g} --rng-seed {a.rng_seed} "
            f"--summary-every-s {a.summary_every_s:g}" + (f" --max-dispatches {a.max_dispatches}" if a.max_dispatches else "")
            + "".join(f" --best-from {Path(x).as_posix()}" for x in a.best_from))


def cmd_plan(lab_root: Path, run1: Path, run2: Path, out: Path, a: argparse.Namespace) -> int:
    params = params_from_args(a)
    P = plan_and_write(lab_root, run1, run2, out, params, best_from=a.best_from)
    p = P["plan"]
    print(json.dumps({k: p[k] for k in ("e7", "best", "archive_set_digest")}, separators=(",", ":"), default=str))
    print(json.dumps({"params": p["params"], "arm": p["arm"]}, separators=(",", ":"), default=str))
    for lv, d in p["archive"]["per_level"].items():
        print("level", lv, json.dumps(d, separators=(",", ":"), default=str))
    x = p["run3"]
    print("run 3 start:", json.dumps({k: x[k] for k in ("groups", "anchors", "demoted", "best_claim", "claims", "niche_stats", "code_digest")}, default=str))
    print(json.dumps({"history_attribution": x["history"]["attribution"], "moves": x["history"]["moves"]}))
    for r in x["start"]:
        if r["eligible"]:
            print(f"  {r['group']:22s} eligible {r['eligible']:5d} anchors {r['anchors']:3d} share {r['share']:.4f} rho {r['rho']:.5f} demoted {r['demoted']} "
                  f"history {r['history']}")
    print(f"wrote {Path(out) / 'plan.json'}")
    print("run with:", run_command(lab_root, run1, run2, out, a))
    return 0


def cmd_run(lab_root: Path, run1: Path, run2: Path, out: Path, a: argparse.Namespace) -> int:
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
    params = params_from_args(a)
    old = json.loads(saved.read_text(encoding="utf-8"))
    P = plan_via_child(lab_root, run1, run2, out, params, code_digest=old.get("run3", {}).get("code_digest"), best_from=a.best_from)
    if old.get("archive_set_digest") != P["plan"]["archive_set_digest"]:
        print("refused: the archive set differs from the saved plan")
        return 2
    if old.get("params") != params.as_dict():
        print(f"refused: the parameters differ from the saved plan's ({old.get('params')})")
        return 2
    if a.check_slots > a.workers:
        print("refused: --check-slots is at most --workers")
        return 2
    install_kill_on_close_job()
    imp = Path(lab_root) / "import"
    frozen = json.loads((imp / "frozen_runtime.json").read_text(encoding="utf-8"))
    cfg = cs.SearchConfig(lab_root=Path(lab_root), out=Path(out), run_dir=run_dir, frontier_dir=Path(run1), n_workers=a.workers, max_ticks=a.max_ticks,
                          max_wall_s=60.0 * a.max_wall_min, expect_code=None)
    text = rx.make_text_replay(imp / "exe" / "BattleShip.exe", run_dir / "text_replays", frozen)
    eng = Run3Night(cfg, fl.real_env(Path(lab_root), run_dir), P, params, text_replay=text,
                    anomaly_build={"exe_sha256": frozen["exe_copy_sha256"].get("BattleShip.exe"), "platform": sys.platform})
    code = eng.run()
    print(f"exit {code}: {run_dir / 'report.md'} (progress: {run_dir / 'progress.md'}, hourly: {run_dir / 'hourly.md'})")
    return code


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("command", choices=("plan", "run"))
    ap.add_argument("--lab-root", default=str(g.DEFAULT_LAB_ROOT))
    ap.add_argument("--run1", required=True, help="run 1's output folder")
    ap.add_argument("--run2", required=True, help="run 2's output folder (planned on --run1)")
    ap.add_argument("--best-from", action="append", default=[], help="a clean run 3 folder whose verified clears join the best and the bound "
                                                                     "(its archive is not inherited); repeatable")
    ap.add_argument("--out", default=None, help="default <lab root>/crossing_<date>_run3")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--level-decay", type=float, default=Params3.level_decay)
    ap.add_argument("--max-segments", type=int, default=Params3.max_segments)
    ap.add_argument("--cleared-weight", type=float, default=Params3.cleared_weight)
    ap.add_argument("--check-slots", type=int, default=Params3.check_slots)
    ap.add_argument("--breadth-share", type=float, default=Params3.breadth_share)
    ap.add_argument("--summary-every-s", type=float, default=Params3.summary_every_s)
    ap.add_argument("--summary-every-dispatches", type=int, default=Params3.summary_every_dispatches)
    ap.add_argument("--max-cells", type=int, default=Params3.max_cells)
    ap.add_argument("--max-dispatches", type=int, default=Params3.max_dispatches)
    ap.add_argument("--rng-seed", type=int, default=Params3.rng_seed)
    ap.add_argument("--max-ticks", type=int, default=cs.SearchConfig.max_ticks)
    ap.add_argument("--max-wall-min", type=float, default=480.0)
    a = ap.parse_args(argv)
    try:
        lab = g.validate_lab_root(Path(a.lab_root))
        out = g.validate_run_dir(Path(a.out) if a.out else lab / f"crossing_{dt.date.today().isoformat()}_run3", lab)
        run1 = g.validate_run_dir(Path(a.run1), lab)
        run2 = g.validate_run_dir(Path(a.run2), lab)
        a.best_from = [g.validate_run_dir(Path(x), lab) for x in a.best_from]
    except g.LabRootError as exc:
        raise SystemExit(str(exc))
    for d in (run1, run2):
        if g.norm(out) == g.norm(d) or g.under(g.norm(out), g.norm(d)):
            raise SystemExit("refused: the output folder is an inherited run's folder (never written)")
    if not 1 <= a.workers <= 5:
        raise SystemExit("refused: 1 to 5 workers (one standby each: at most 10 game processes)")
    if not 1 <= a.check_slots <= a.workers:
        raise SystemExit("refused: --check-slots is 1 to --workers")
    if a.max_ticks < 1 or a.max_wall_min <= 0:
        raise SystemExit("refused: --max-ticks and --max-wall-min are positive")
    try:
        params_from_args(a)
    except SearchError as exc:
        raise SystemExit(str(exc))
    if not (lab / "import" / "import_manifest.json").is_file():
        raise SystemExit("refused: no lab import (rl/frs_lab.py import first)")
    g.LabGuard.install(lab)
    lock = g.LabLock(lab, f"crossing_search_run3 {a.command}")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        print(str(exc))
        return 2
    try:
        if a.command == "plan":
            return cmd_plan(lab, run1, run2, out, a)
        return cmd_run(lab, run1, run2, out, a)
    except (SearchError, rl3.LoadError) as exc:
        print(str(exc))
        return 3
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
