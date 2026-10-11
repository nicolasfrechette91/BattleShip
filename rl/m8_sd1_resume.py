"""M8-sd1 resume: the open protocol of the first time-directed continuation, five levels deep (zero native ticks), and the close checks.

rd4's protocol (rl/m8_rd4_resume.py, unchanged and reused wherever generic) resumed rd3's closed tree. sd1 resumes rd4's closed tree, which continues rd3's, rd2's and rd1's:

    R1  immutability of ALL FOUR earlier trees: runs/m8_rd/, runs/m8_rd_rd2/, runs/m8_rd_rd3/ and runs/m8_rd_rd4/ each hold exactly the files of their D: increment (paths, sizes,
        mtimes, sha256 and the backup's own bytes), each increment's record says PASS
    R2  rd1's, rd2's and rd3's archive facts (their own audits) and rd4's closing archive facts: manifest verified, checkpoint 45 / previous 44, the five files equal rd4's close record,
        the counts (37,312 cells, 13,886 bursts, 27,775 events), the dispatch iterations 0..13,885 contiguous, no `fail` event, exactly three `session` events (rd2 and rd3 with the
        v2 digest, rd4 with the v3 digest, each RECOMPUTED from the current contracts), the diag2 counters equal rd4's close record, rd4's recorded decision (PROGRESS, m 4), and the
        INHERITED RECORD FACTS that replace rd4's claim preconditions: the best verified clear (completion_input_tick 2,315 / completion_time_passed 2,314, claim t, cid 239, iteration
        11286, native action digest de1228be...), the other verified clear (2,326 / 2,325), the four level-10 cells, every level's count and shortest arrival, the left-floor landings,
        rd4's claim facts, the clear-event trajectories rd4 registered and which of them no rd4 replay verified (the rule of rl/m8_sd1_claims.py), and rd5's status. Any difference
        refuses the session
    R3  the pins equal the archives' (executable, runtime files, frozen configuration, flags, each session's own contract set: rd1 six keys, rd2 and rd3 seven, rd4 eight)
    R4  the ledger rebuild of rd4's closing archive (rd4's own `audit4`: rd1 under v1, rd2 and rd3 under v2, rd4 under v3, zero ticks) and the prefix chain rd1 -> rd2 -> rd3 -> rd4
    R5  rd4's closing overlay reproduced (the v2 flags of every cell, computed twice and equal, equal to the counts rd4's close record stores and to the registered figures and digest),
        AND sd1's own open overlay under v4 (E7 applied), computed twice and equal, its counts and digest registered: eligibility changes under v4, so the open overlay is new
    R6  materialise runs/m8_rd_sd1/: rd4's five closing data files and manifest copied byte for byte into base/, both overlays and a stamped companion record, a stamped base record,
        sd1's `session` event (v4, the record reference, the margin) and the first sd1 checkpoint (sequence 46) whose archive_meta.json is stamped once, with created_utc fixed here

Nothing here writes under any earlier tree (a static test guards that). The four trees are only read.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_resume as rs  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd4_resume as r4  # noqa: E402
import m8_rd4_select as s4  # noqa: E402
import m8_sd1_artifacts as art  # noqa: E402
import m8_sd1_claims as cl5  # noqa: E402
import m8_sd1_select as s5  # noqa: E402

RESUME5_CONTRACT = "m8_sd1_resume_v1"
RD4_INCREMENT_NAME = "2026-10-03_incr_m8_rd4"
RD4_INCREMENT_MANIFEST_SHA256 = "7ff2b29dfad2bcaa26e2567786acc3c84c55a6414501545b0f1c1815480068a8"
RECORD_SOURCE = "sessions/rd4/verification/replays.jsonl: exact clear replay of candidate 239 (kind t, iteration 11286) of rd4"
# the archive's best VERIFIED clear before sd1 (rd4 claim t, cid 239, iteration 11286; route runs/m8_rd_rd4/routes/T_t): the selection's E7 and the rule read these numbers, pinned at the open
RECORD_REFERENCE = s5.record_reference_block(completion_input_tick=2315, completion_time_passed=2314, native_action_digest="de1228be4146b720adc3f1272a9e65a8c0dcd7882b83134949f3893adfef8045",
                                             words=2315, cid=239, iteration=11286, kind="t", session="rd4", source=RECORD_SOURCE)
# the inherited record facts (the archive's own structure, read from rd4's closed tree; no census threshold)
INHERITED_RECORD: Dict[str, Any] = {
    "best_verified": dict(RECORD_REFERENCE),
    "verified_clears": [{"cid": 239, "iteration": 11286, "kind": "t", "completion_input_tick": 2315, "completion_time_passed": 2314, "native_action_digest": RECORD_REFERENCE["native_action_digest"], "words": 2315},
                        {"cid": 194, "iteration": 11206, "kind": "left", "completion_input_tick": 2326, "completion_time_passed": 2325,
                         "native_action_digest": "5eccd4e2d5d77b25d69a2ae87211c05f8c7349fdeeeed6e094b53a88003907ba", "words": 2326}],
    "clear_event_candidates": 10, "clear_trajectories_registered": 5,
    "unverified_clear_trajectories": [{"iteration": 12559, "first_clear": 2324}, {"iteration": 12823, "first_clear": 2341}, {"iteration": 12146, "first_clear": 2348}],
    "levels": {"0": {"cells": 1766, "min_L": 0}, "1": {"cells": 2767, "min_L": 26}, "2": {"cells": 3297, "min_L": 91}, "3": {"cells": 4591, "min_L": 152}, "4": {"cells": 5418, "min_L": 254},
               "5": {"cells": 4845, "min_L": 584}, "6": {"cells": 4274, "min_L": 931}, "7": {"cells": 5107, "min_L": 1339}, "8": {"cells": 2342, "min_L": 1838}, "9": {"cells": 2901, "min_L": 1898},
               "10": {"cells": 4, "min_L": 2315}},
    "level_10_L": [2315, 2324, 2326, 2348], "top_eligible_level": {"level": 9, "min_L": 1898, "min_cell": 30042},
    "left_floor_grounded": {"cells": 15, "min_L": 1911},          # every level (the proposal's "five at 1,966" is the level-9 subset)
    "claim_facts": {"wall_top_cell_ids": [18318, 18767, 26944], "cells_left_of_boundary": None, "grounded_cells_on_left_floor": 15, "cells_with_a_left_target_broken": None, "max_level": 10},
    "rd4_outcome": "PROGRESS", "rd4_m": 4, "rd5_permitted": True}
RD4_FACTS = {"files": 93, "bytes": 165_147_441, "increment_manifest_sha256": RD4_INCREMENT_MANIFEST_SHA256, "cells": 37312, "bursts": 13886, "events": 27775, "checkpoint_seq": 45,
             "previous_checkpoint_seq": 44, "exploration_ticks": 5_590_384, "dispatch_iterations": (0, 13885), "contiguous": True, "first_rd2_iteration": 2175, "first_rd3_iteration": 6212, "first_rd4_iteration": 10406,
             "first_sd1_iteration": 13886, "returns": 3480, "rd4_cells_created": 10941, "outcome": "PROGRESS", "m": 4, "inherited_record": INHERITED_RECORD}
# rd4's closing overlay (its close record, `archive.overlay_close`): the headline figures the open must reproduce exactly
EXPECTED_RD4_CLOSE_OVERLAY = {"cells": 37312, "eligible_v1": 30506, "descent_among_v1_eligible": 5053, "bound_among_v1_eligible": 3796, "union": 8050, "eligible_v2": 22456,
                              "launch_capable_cells": 857, "grounded_cells": 629, "step_contact_cells": 97, "still_eligible": {"launch_capable": 770, "step_contact": 97, "grounded": 629}}
RD4_CLOSING_OVERLAY_SHA256 = "c6b8d52db89c217e47078d61c0cde19531107dc675fec9106f3d5fc835a5cbfe"     # as computed at the preparation (a test and the approval pin it)
# sd1's own open overlay under v4 (E7 applied at L <= 2,290): the registered figures, computed at the preparation (a test and the approval pin them). E7 excludes 323 cells (293 at level 9,
# 26 at level 8, the 4 terminal level-10 cells), 286 of them eligible under v3 (284 at level 9, 2 at level 8): 23,539 v3-eligible cells become 23,253 v4-eligible ones.
EXPECTED_OPEN_OVERLAY5: Dict[str, Any] = {
    "cells": 37312, "eligible_v1": 30506, "descent_among_v1_eligible": 5053, "bound_among_v1_eligible": 3796, "union": 8050, "eligible_v2": 22456, "eligible_v3": 23539, "eligible_v4": 23253,
    "bound_L": 2290, "record_bound_cells": 323, "record_bound_among_v3_eligible": 286,
    "record_bound_by_level": {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0, "8": 26, "9": 293, "10": 4},
    "record_bound_among_v3_eligible_by_level": {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0, "8": 2, "9": 284, "10": 0},
    "eligible_v4_by_level": {"0": 935, "1": 2061, "2": 2412, "3": 2999, "4": 2862, "5": 2907, "6": 2124, "7": 3477, "8": 929, "9": 2547, "10": 0},
    "shortest_L_by_level": {"0": 0, "1": 26, "2": 91, "3": 152, "4": 254, "5": 584, "6": 931, "7": 1339, "8": 1838, "9": 1898, "10": 2315},
    "shortest_eligible_L_by_level": {"0": 0, "1": 26, "2": 91, "3": 152, "4": 254, "5": 584, "6": 931, "7": 1339, "8": 1838, "9": 1898, "10": None}}
SD1_OPEN_OVERLAY_SHA256 = "a5d0af34a00b115e3a545826fe787355da5ef6594185b72ffaa30586cc2c176c"


class Resume5Error(RuntimeError):
    """The open protocol failed (the session is refused, nothing runs)."""


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# -- prior sessions' records (read, never assumed) ----------------------------------------------------------------------------------------------------


def prior_milestones5(rd1_dir: Path, rd2_dir: Path, rd3_dir: Path, rd4_dir: Path) -> Dict[str, Any]:
    out = dict(r4.prior_milestones(rd1_dir, rd2_dir, rd3_dir))
    p = Path(rd4_dir) / "sessions" / "rd4" / "rule.json"
    if p.is_file():
        r = _read(p)
        out["rd4"] = {"m": int(r["m"]), "milestone": r.get("highest_milestone", r.get("milestone")), "outcome": r.get("outcome"), "source": "sessions/rd4/rule.json"}
    else:
        out["rd4"] = None
    return out


def rd4_line_status(rd4_dir: Path, session: str = "rd4") -> Dict[str, Any]:
    """rd4's recorded line status (rd5 permitted or not), read from its own rule record; a missing record is refused by the caller (None), never defaulted."""
    p = Path(rd4_dir) / "sessions" / session / "rule.json"
    if not p.is_file():
        return {"rd5_permitted": None, "status": None, "source": None, "missing": True}
    r = _read(p)
    line = r.get("line") or {}
    return {"rd5_permitted": line.get("rd5_permitted"), "status": line.get("status"), "line_ends": line.get("line_ends"), "source": f"sessions/{session}/rule.json", "missing": False}


# -- the inherited record facts ---------------------------------------------------------------------------------------------------------------------------


def verified_clears_of(rd4_dir: Path, session: str = "rd4") -> List[Dict[str, Any]]:
    """Every exact clear replay of rd4 (its replays.jsonl), with both clocks and the digest of its registered words (the clear-kind twin of a `left`/`t` candidate shares its trajectory)."""
    tr = cl5.clear_trajectories(rd4_dir, session)
    words = cl5.registry_words(rd4_dir, session)
    out: List[Dict[str, Any]] = []
    for r in cl5.rd4_replays(rd4_dir, session):
        if not (r.get("exact") and r.get("clear")):
            continue
        c = tr["candidates_by_cid"].get(int(r["cid"]))
        if c is None:
            raise Resume5Error(f"{session}'s replay of candidate {r['cid']} has no registry entry")
        w = words[int(c["cid"])]
        if c["kind"] == "t":
            w = w[:int(c["event_j"])]
        w = w[:int(r["counted"])]
        facts = r.get("clear_facts") or {}
        out.append({"cid": int(c["cid"]), "iteration": int(c["iteration"]), "kind": c["kind"], "completion_input_tick": int(facts["completion_input_tick"]),
                    "completion_time_passed": int(facts["completion_time_passed"]), "native_action_digest": mcell.words_digest(w), "words": len(w)})
    out.sort(key=lambda v: (v["completion_input_tick"], v["cid"]))
    return out


def record_reference_from(rd4_dir: Path, session: str = "rd4") -> Dict[str, Any]:
    """The archive's best verified clear, read from rd4's own records: the exact clear replay with the smallest completion_input_tick (then cid)."""
    vc = verified_clears_of(rd4_dir, session)
    if not vc:
        raise Resume5Error(f"{session} holds no exact clear replay: there is no record reference to search below")
    b = vc[0]
    return s5.record_reference_block(completion_input_tick=b["completion_input_tick"], completion_time_passed=b["completion_time_passed"], native_action_digest=b["native_action_digest"],
                                     words=b["words"], cid=b["cid"], iteration=b["iteration"], kind=b["kind"], session=session,
                                     source=f"sessions/{session}/verification/replays.jsonl: exact clear replay of candidate {b['cid']} (kind {b['kind']}, iteration {b['iteration']}) of {session}")


def inherited_record_facts(rd4_dir: Path, a: march.Archive, session: str = "rd4") -> Dict[str, Any]:
    """The archive's own structure and rd4's own records, as INHERITED_RECORD pins them."""
    rr = record_reference_from(rd4_dir, session)
    tr = cl5.clear_trajectories(rd4_dir, session)
    levels = sorted({c.level for c in a.cells})
    top = max((c.level for c in a.cells if a.eligible(c)), default=0)
    top_cells = [c for c in a.cells if c.level == top and a.eligible(c)]
    short = min(top_cells, key=lambda c: (c.L, c.id)) if top_cells else None
    lf = [c for c in a.cells if c.key[2] == mcell.RES_GROUNDED and c.key[4] in mcell.LEFT_FLOOR_LINES]
    claim = dict(r4.inherited_claim_facts(a))
    line = rd4_line_status(rd4_dir, session)
    rule_p = Path(rd4_dir) / "sessions" / session / "rule.json"
    rule = _read(rule_p) if rule_p.is_file() else {}
    return {"best_verified": rr, "verified_clears": verified_clears_of(rd4_dir, session),
            "clear_event_candidates": sum(1 for c in tr["candidates_by_cid"].values() if cl5.clear_tick(c) is not None), "clear_trajectories_registered": len(tr["jobs"]),
            "unverified_clear_trajectories": [{"iteration": j["iteration"], "first_clear": j["first_clear"]} for j in tr["jobs"] if not j["verified_by_rd4"]],
            "levels": {str(lv): {"cells": sum(1 for c in a.cells if c.level == lv), "min_L": min(c.L for c in a.cells if c.level == lv)} for lv in levels},
            "level_10_L": sorted(c.L for c in a.cells if c.level == mcell.TARGETS_TOTAL),
            "top_eligible_level": {"level": top, "min_L": short.L if short else None, "min_cell": short.id if short else None},
            "left_floor_grounded": {"cells": len(lf), "min_L": min((c.L for c in lf), default=None)},
            "claim_facts": {"wall_top_cell_ids": claim["wall_top_cell_ids"], "cells_left_of_boundary": None, "grounded_cells_on_left_floor": claim["grounded_cells_on_left_floor"],
                            "cells_with_a_left_target_broken": None, "max_level": claim["max_level"]},
            "rd4_outcome": rule.get("outcome"), "rd4_m": rule.get("m"), "rd5_permitted": line.get("rd5_permitted")}


def record_fact_problems(facts: Mapping[str, Any], expect: Mapping[str, Any]) -> List[str]:
    """Every difference between the inherited record facts read from the tree and the registered ones (keys the registered set carries only; a None in the registered set is unchecked)."""
    out: List[str] = []
    for k, want in expect.items():
        got = facts.get(k)
        if isinstance(want, Mapping) and isinstance(got, Mapping):
            for kk, vv in want.items():
                if vv is None:
                    continue
                if json.dumps(got.get(kk), sort_keys=True) != json.dumps(vv, sort_keys=True):
                    out.append(f"inherited record {k}.{kk}: {got.get(kk)} differs from the registered {vv}")
        elif json.dumps(got, sort_keys=True, default=str) != json.dumps(want, sort_keys=True, default=str):
            out.append(f"inherited record {k}: {json.dumps(got, default=str)[:200]} differs from the registered {json.dumps(want, default=str)[:200]}")
    if facts.get("best_verified") is None:
        out.append("no verified clear: no record reference")
    return out


# -- R2 / R4: rd4's closing archive --------------------------------------------------------------------------------------------------------------------------


def rd4_archive_facts(rd1_dir: Path, rd2_dir: Path, rd3_dir: Path, rd4_dir: Path, lines_sha256: Optional[str] = None, expect: Optional[Mapping[str, Any]] = None, *,
                      with_audit: bool = True, keep_archive: bool = False) -> Dict[str, Any]:
    """Read and audit rd4's closing archive with rd4's own code: manifest, checkpoints, close record, counts, the three session events and their digests, the iterations, the ledger audit,
    the prefix chain rd1 -> rd2 -> rd3 -> rd4 and the inherited record facts. `expect` = the registered facts (RD4_FACTS; a parameter for the tests on synthetic trees only)."""
    E = dict(RD4_FACTS if expect is None else expect)
    rd1_dir, rd2_dir, rd3_dir, rd4_dir = Path(rd1_dir), Path(rd2_dir), Path(rd3_dir), Path(rd4_dir)
    problems: List[str] = []
    best, meta, report = march.load_latest_verified(rd4_dir / "archive")
    seqs = {r["dir"]: r.get("checkpoint_seq") for r in report if r["state"] == "verified"}
    if best is None or meta is None:
        return {"ok": False, "problems": ["no verified checkpoint"], "checkpoints": report}
    if Path(best).name != "archive" or int(meta["checkpoint_seq"]) != E["checkpoint_seq"] or seqs.get("archive.prev") != E["previous_checkpoint_seq"]:
        problems.append(f"checkpoints {seqs} (best {Path(best).name}), expected {E['checkpoint_seq']} / {E['previous_checkpoint_seq']}")
    a, meta = s5.Archive5.read_dir(rd4_dir / "archive")
    lines = str(lines_sha256 if lines_sha256 is not None else (meta.get("pin_tick0") or {}).get("lines"))
    counts = (len(a.cells), len(a.bursts), len(a.events))
    if counts != (E["cells"], E["bursts"], E["events"]):
        problems.append(f"counts {counts}, expected {(E['cells'], E['bursts'], E['events'])}")
    close_p = rd4_dir / "sessions" / "rd4" / "close.json"
    close = _read(close_p) if close_p.is_file() else {}
    manifest = {n: march.sha256_file(rd4_dir / "archive" / n) for n in march.DATA_FILES}
    if (close.get("archive") or {}).get("manifest") != manifest:
        problems.append("the archive's files differ from rd4's close record")
    if (close.get("archive") or {}).get("checkpoint_seq") != E["checkpoint_seq"]:
        problems.append("the close record's checkpoint sequence differs")
    state_p = rd4_dir / "sessions" / "rd4" / "state.json"
    if not state_p.is_file() or _read(state_p).get("phase") != "done":
        problems.append("rd4's session state is not done")
    rule_p = rd4_dir / "sessions" / "rd4" / "rule.json"
    rule_rec = _read(rule_p) if rule_p.is_file() else {}
    if "outcome" in E and (rule_rec.get("outcome") != E["outcome"] or rule_rec.get("m") != E["m"]):
        problems.append(f"rd4's recorded decision {rule_rec.get('outcome')!r} m={rule_rec.get('m')!r} differs from the registered {E['outcome']!r} m={E['m']!r}")
    lt = meta.get("ledger_T") or {}
    if "returns" in E and (lt.get("jobs") != E["returns"] or lt.get("ticks") != E["exploration_ticks"]):
        problems.append(f"rd4's ledger totals {lt} differ from the registered {E['returns']} returns / {E['exploration_ticks']} ticks")
    if meta.get("archive_id") != rs.RD1_ARCHIVE_ID or meta.get("schema") != s2.ARCHIVE_SCHEMA_V2 or meta.get("mode") != 2 or meta.get("select3_contract") != s4.SELECT3_CONTRACT:
        problems.append("archive id, schema, mode or select contract differs")
    sess = [e for e in a.events if e["ev"] == "session"]
    v2_now = s2.select2_contract_digest(a.clf.table_sha256, lines, a.floor_min)
    v3_now = s4.select3_contract_digest(a.clf.table_sha256, lines, a.floor_min)
    if [(e.get("name"), int(e["first_iteration"])) for e in sess] != [("rd2", E["first_rd2_iteration"]), ("rd3", E["first_rd3_iteration"]), ("rd4", E["first_rd4_iteration"])]:
        problems.append(f"session events {[(e.get('name'), e.get('first_iteration')) for e in sess]}, expected rd2 at {E['first_rd2_iteration']}, rd3 at {E['first_rd3_iteration']} and rd4 at {E['first_rd4_iteration']}")
    else:
        if sess[0]["digest"] != v2_now or sess[1]["digest"] != v2_now:
            problems.append("rd2's or rd3's session digest differs from the v2 digest recomputed from the current contract (they did not run v2 unchanged)")
        if sess[2]["digest"] != v3_now:
            problems.append("rd4's session digest differs from the v3 digest recomputed from the current contract (rd4 did not run v3 unchanged)")
    its = sorted(e["it"] for e in a.events if e["ev"] == "dispatch")
    if E.get("contiguous", True):
        if its != list(range(E["dispatch_iterations"][0], E["dispatch_iterations"][1] + 1)):
            problems.append(f"the dispatch iterations are not the contiguous {E['dispatch_iterations'][0]}..{E['dispatch_iterations'][1]}")
    elif not its or its != sorted(set(its)) or (its[0], its[-1]) != tuple(E["dispatch_iterations"]):
        problems.append(f"the dispatch iterations are not strictly increasing from {E['dispatch_iterations'][0]} to {E['dispatch_iterations'][1]}")
    if any(e["ev"] == "fail" for e in a.events):
        problems.append("the ledger holds fail events")
    d4 = close.get("archive", {}).get("diag2") or {}
    cur = {k: (len(v) if isinstance(v, list) else v) for k, v in a.diag2.items()}
    if cur != d4:
        problems.append(f"the diag2 counters {cur} differ from rd4's close record {d4}")
    base_ok = True
    for n in (*march.DATA_FILES, march.MANIFEST):
        pa, pb = rd4_dir / "base" / n, rd3_dir / "archive" / n
        if not (pa.is_file() and pb.is_file() and march.sha256_file(pa) == march.sha256_file(pb)):
            base_ok = False
    if not base_ok:
        problems.append("rd4's base copy differs from rd3's closing archive files")
    chain = r4.prefix_chain(rd1_dir / "archive", rd2_dir / "archive", rd3_dir / "archive", rd4_dir / "archive")
    if not chain["ok"]:
        problems += [f"prefix chain: {p}" for p in chain["problems"]]
    try:
        inh = inherited_record_facts(rd4_dir, a)
        rr = inh["best_verified"]
    except (Resume5Error, ValueError, KeyError, OSError) as exc:
        inh, rr = {}, None
        problems.append(f"the inherited record facts could not be read: {type(exc).__name__}: {exc}")
    if inh and "inherited_record" in E:
        problems += record_fact_problems(inh, E["inherited_record"])
    if rr is not None and rr["completion_input_tick"] != rr["words"]:
        problems.append("the record reference's clock differs from its word count")
    line = rd4_line_status(rd4_dir)
    if line.get("missing"):
        problems.append("rd4's rule record (the rd line status) is missing")
    aud: Dict[str, Any] = {"skipped": True}
    if with_audit:
        aud = s4.audit4(a, lines)
        if not aud["ok"]:
            problems += [f"rd4 audit: {p}" for p in aud["problems"][:5]]
    return {"ok": not problems, "problems": problems, "checkpoints": seqs, "counts": {"cells": counts[0], "bursts": counts[1], "events": counts[2]}, "manifest": manifest,
            "close_record_sha256": rs.sha256_file(close_p) if close_p.is_file() else None, "audit": aud, "session_events": sess, "digest_recomputed": {"v2": v2_now, "v3": v3_now},
            "dispatch_iterations": [its[0], its[-1]] if its else None, "diag2": cur, "prefix_chain": chain, "pin_tick0": meta.get("pin_tick0"), "pins": meta.get("pins"),
            "ticks": meta.get("ticks"), "ledger_T": meta.get("ledger_T"), "rd4_checkpoint_seq": int(meta["checkpoint_seq"]), "first_sd1_iteration": (its[-1] + 1) if its else 0,
            "lines_sha256": lines, "inherited_record": inh, "record_reference": rr, "rd4_line": line, "archive": a if keep_archive else None}


# -- R5: the two overlays ---------------------------------------------------------------------------------------------------------------------------------------


def build_overlay5(archive_dir: Path, record_reference: Mapping[str, Any], margin: int, floor_min: Optional[float] = None) -> Dict[str, Any]:
    """rd4's closing overlay (v2's flags, which v3 kept) and sd1's open overlay (v4: E7 applied), each computed twice (the incremental structures of one load and the first-principles
    recomputation of another) and required equal, with their bytes, digests and counts."""
    t_rec = int(record_reference["completion_input_tick"])
    a, _m = s5.Archive5.read_dir(Path(archive_dir), floor_min=floor_min)
    b, _m2 = s5.Archive5.read_dir(Path(archive_dir), floor_min=floor_min)
    desc, bound = b.reference_flags()
    rows2_a, rows2_b = s2.overlay_rows(a), s2.overlay_rows(b, desc, bound)
    rows5_a, rows5_b = s5.overlay_rows5(a, t_rec, margin), s5.overlay_rows5(b, t_rec, margin, desc, bound)
    b2a, b2b = s2.overlay_bytes(rows2_a), s2.overlay_bytes(rows2_b)
    b5a, b5b = s5.overlay_bytes5(rows5_a), s5.overlay_bytes5(rows5_b)
    problems: List[str] = []
    if b2a != b2b:
        problems.append("rd4's closing overlay computed twice differs")
    if b5a != b5b:
        problems.append("sd1's open overlay computed twice differs")
    return {"ok": not problems, "problems": problems,
            "rd4_closing": {"rows": rows2_a, "bytes": b2a, "sha256": hashlib.sha256(b2a).hexdigest(), "counts": s2.overlay_counts(a, rows2_a)},
            "v4": {"rows": rows5_a, "bytes": b5a, "sha256": hashlib.sha256(b5a).hexdigest(), "counts": s5.overlay_counts5(a, rows5_a, t_rec, margin)},
            "record_reference": dict(record_reference), "margin": int(margin)}


def closing_overlay5(rd4_dir: Path, record_reference: Mapping[str, Any], margin: int, expect_rd4: Optional[Mapping[str, Any]] = None, expect_v4: Optional[Mapping[str, Any]] = None,
                     floor_min: Optional[float] = None, *, rd4_sha256: Optional[str] = None, v4_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Both overlays of rd4's closing archive, compared with the overlay counts rd4's close record stores, the registered headline figures and (when given) the pinned digests."""
    rd4_dir = Path(rd4_dir)
    ov = build_overlay5(rd4_dir / "archive", record_reference, margin, floor_min)
    problems = list(ov["problems"])
    close_p = rd4_dir / "sessions" / "rd4" / "close.json"
    stored = (_read(close_p).get("archive") or {}).get("overlay_close") if close_p.is_file() else None
    if stored is None:
        problems.append("rd4's close record holds no closing overlay")
    elif json.dumps(ov["rd4_closing"]["counts"], sort_keys=True) != json.dumps(stored, sort_keys=True):
        problems.append("rd4's closing overlay counts differ from rd4's close record")
    for k, v in (EXPECTED_RD4_CLOSE_OVERLAY if expect_rd4 is None else expect_rd4).items():
        if json.dumps(ov["rd4_closing"]["counts"].get(k), sort_keys=True) != json.dumps(v, sort_keys=True):
            problems.append(f"rd4 closing overlay {k}: {ov['rd4_closing']['counts'].get(k)} (registered {v})")
    for k, v in (EXPECTED_OPEN_OVERLAY5 if expect_v4 is None else expect_v4).items():
        if json.dumps(ov["v4"]["counts"].get(k), sort_keys=True) != json.dumps(v, sort_keys=True):
            problems.append(f"sd1 open overlay {k}: {ov['v4']['counts'].get(k)} (registered {v})")
    if rd4_sha256 is not None and ov["rd4_closing"]["sha256"] != rd4_sha256:
        problems.append(f"rd4's closing overlay sha256 {ov['rd4_closing']['sha256']} differs from the registered {rd4_sha256}")
    if v4_sha256 is not None and ov["v4"]["sha256"] != v4_sha256:
        problems.append(f"sd1's open overlay sha256 {ov['v4']['sha256']} differs from the registered {v4_sha256}")
    out = dict(ov, ok=not problems, problems=problems, stored_close_counts=stored)
    return out


# -- R6: materialise ---------------------------------------------------------------------------------------------------------------------------------------------


def materialise5(rd4_dir: Path, new_root: Path, *, facts: Mapping[str, Any], overlay: Mapping[str, Any], lines_sha256: str, meta_extra: Mapping[str, Any], increment_manifest_sha256: str,
                 utc: str, margin: int, floor_min: Optional[float] = None) -> s5.Archive5:
    """Create sd1's tree: base/ (rd4's closing data files and manifest, byte for byte), derived/ (both overlays, their stamped companion record, the stamped base record) and the first
    sd1 checkpoint in archive/ (rd4's cells and ledger plus sd1's `session` event), whose archive_meta.json carries the stamp with created_utc = `utc`, fixed here for every later
    checkpoint. Returns the archive (mode 2, sd1 begun)."""
    rd4_dir, new_root = Path(rd4_dir), Path(new_root)
    if new_root.exists():
        raise Resume5Error(f"{new_root} exists (never overwritten)")
    rr = dict(facts["record_reference"])
    s5.validate_record_reference(rr)
    (new_root / "base").mkdir(parents=True)
    (new_root / "derived").mkdir()
    base_hashes: Dict[str, str] = {}
    for n in (*march.DATA_FILES, march.MANIFEST):
        src, dst = rd4_dir / "archive" / n, new_root / "base" / n
        shutil.copyfile(src, dst)
        base_hashes[n] = rs.sha256_file(dst)
        if base_hashes[n] != rs.sha256_file(src):
            raise Resume5Error(f"the base copy of {n} differs from rd4's file")
    if march.verify_manifest(new_root / "base"):
        raise Resume5Error("the base copy's manifest does not verify")
    a, _meta = s5.Archive5.read_dir(new_root / "base", floor_min=floor_min)
    for name, part in (("rd4_closing_overlay.jsonl", overlay["rd4_closing"]), ("open_overlay.jsonl", overlay["v4"])):
        p = new_root / "derived" / name
        p.write_bytes(part["bytes"])
        if hashlib.sha256(p.read_bytes()).hexdigest() != part["sha256"]:
            raise Resume5Error(f"the stored overlay {name} differs from its digest")
    art.write_json5(new_root / "derived" / "open_overlay.json", {
        "kind": "sd1's open overlay under m8_rd_select_v4 (E7 applied) and rd4's closing overlay (v2's flags, kept by v3), both of rd4's closing archive, each computed twice and equal",
        "open_overlay": {"file": "open_overlay.jsonl", "sha256": overlay["v4"]["sha256"], "counts": overlay["v4"]["counts"], "rows": len(overlay["v4"]["rows"])},
        "rd4_closing_overlay": {"file": "rd4_closing_overlay.jsonl", "sha256": overlay["rd4_closing"]["sha256"], "counts": overlay["rd4_closing"]["counts"], "rows": len(overlay["rd4_closing"]["rows"])},
        "record_reference": rr, "margin": int(margin), "utc": utc, "computed_twice_equal": True}, created_utc=utc)
    ev = a.begin_sd1(int(facts["first_sd1_iteration"]), lines_sha256, rr, int(margin))
    base = {"schema": "m8_sd1_base_v1", "rd4_checkpoint_seq": facts.get("rd4_checkpoint_seq"), "rd4_archive_files_sha256": dict(base_hashes), "rd4_close_record_sha256": facts.get("close_record_sha256"),
            "rd4_manifest": facts.get("manifest"), "rd4_increment": RD4_INCREMENT_NAME, "rd4_increment_manifest_sha256": increment_manifest_sha256, "session_event": ev,
            "open_overlay_sha256": overlay["v4"]["sha256"], "rd4_closing_overlay_sha256": overlay["rd4_closing"]["sha256"], "inherited_record": facts.get("inherited_record"),
            "rd4_line": facts.get("rd4_line"), "utc": utc}
    art.write_json5(new_root / "derived" / "base.json", base, created_utc=utc)
    meta = art.stamp(dict(meta_extra, checkpoint_seq=int(facts["rd4_checkpoint_seq"]) + 1, why="open", utc=utc, session="sd1", base=base), created_utc=utc)
    march.save_checkpoint(new_root / "archive", a, meta)
    pp = rs.prefix_property(rd4_dir / "archive", new_root / "archive")                    # sd1's ledger begins with rd4's exact bytes, from the first checkpoint on
    if not pp["ok"]:
        raise Resume5Error(f"sd1's first checkpoint does not begin with rd4's closing bytes: {pp['problems']}")
    written = _read(new_root / "archive" / "archive_meta.json")
    if written.get("created_utc") != utc or not art.is_stamped(written):
        raise Resume5Error("the materialised archive_meta.json is not stamped with the materialisation time")
    return a


# -- close: the prefix chain ------------------------------------------------------------------------------------------------------------------------------------


def prefix_chain(rd1_archive: Path, rd2_archive: Path, rd3_archive: Path, rd4_archive: Path, sd1_archive: Path) -> Dict[str, Any]:
    """rd2's archive files begin with rd1's bytes, rd3's with rd2's closing bytes, rd4's with rd3's and sd1's with rd4's (every ledger line, burst index row and word)."""
    four = r4.prefix_chain(Path(rd1_archive), Path(rd2_archive), Path(rd3_archive), Path(rd4_archive))
    d = rs.prefix_property(Path(rd4_archive), Path(sd1_archive))
    return {"rd1_rd2": four["rd1_rd2"], "rd2_rd3": four["rd2_rd3"], "rd3_rd4": four["rd3_rd4"], "rd4_sd1": d, "ok": bool(four["ok"] and d["ok"]),
            "problems": list(four["problems"]) + [f"rd4->sd1: {p}" for p in d["problems"]]}
