"""M8-sd2 resume: the open protocol of the second time-directed continuation, six levels deep (zero native ticks), and the close checks.

sd1's protocol (rl/m8_sd1_resume.py, unchanged and reused wherever generic) resumed rd4's closed tree. sd2 resumes sd1's closed tree, which continues rd4's, rd3's, rd2's and rd1's:

    R1  immutability of ALL FIVE earlier trees: runs/m8_rd/, runs/m8_rd_rd2/, runs/m8_rd_rd3/, runs/m8_rd_rd4/ and runs/m8_rd_sd1/ each hold exactly the files of their D: increment
        (paths, sizes, mtimes, sha256 and the backup's own bytes), each increment's record says PASS
    R2  rd1's to rd4's archive facts (sd1's own protocol, reused) and sd1's closing archive facts: manifest verified, checkpoint 57 / previous 56, the five files equal sd1's close record,
        the counts (44,007 cells, 17,554 bursts, 35,118 events), the dispatch iterations 0..17,556 contiguous, no `fail` event, exactly four `session` events (rd2 and rd3 with the v2
        digest, rd4 with the v3 digest, sd1 with the v4 digest AT SD1'S OWN REFERENCE, each RECOMPUTED from the current contracts), the diag2 counters equal sd1's close record, sd1's
        recorded decision and line (PROGRESS, SD2_PROPOSABLE_NEW_REFERENCE, counted), sd1's base copy equal to rd4's closing files, and the INHERITED RECORD FACTS: the best verified
        clear (completion_input_tick 2,086 / completion_time_passed 2,085, candidate 901, kind clear, iteration 15795, native action digest a2a85903...), the five level-10 cells,
        every level's count and shortest arrival, the left-floor landings, the wall-top cells, the clear-event trajectories sd1 registered and which of them no sd1 replay verified
        (none: the rule of rl/m8_sd2_claims.py), sd1's three inherited descriptive replays (all exact), and the rd line's status as sd1 copied it. Any difference refuses the session
    R3  the pins equal the archives' (executable, runtime files, frozen configuration, flags, each session's own contract set: rd1 six keys, rd2 and rd3 seven, rd4 eight, sd1 nine with
        m8_rd_select_v4 at sd1's reference)
    R4  the ledger rebuild of sd1's closing archive (`audit6`: rd1 under v1, rd2 and rd3 under v2, rd4 under v3, sd1 under v4 at sd1's bound, zero ticks) and the prefix chain
        rd1 -> rd2 -> rd3 -> rd4 -> sd1
    R5  sd1's closing overlay under v4 at sd1's reference reproduced (computed twice and equal, equal to the counts sd1's close record stores and to the registered figures and digest),
        AND sd2's own open overlay under v4 at the new reference (E7 at L <= 2,061), computed twice and equal, its counts and digest registered
    R6  materialise runs/m8_rd_sd2/: sd1's five closing data files and manifest copied byte for byte into base/, both overlays and a stamped companion record, a stamped base record,
        sd2's `session` event (v4 at the new reference, with sd1's digest beside it) and the first sd2 checkpoint (sequence 58) whose archive_meta.json is stamped once, with
        created_utc fixed here

INTEGRITY LITERALS. `SD1_FACTS`, `INHERITED_RECORD6`, `EXPECTED_SD1_CLOSE_OVERLAY_V4` and `EXPECTED_OPEN_OVERLAY6` pin the STRUCTURE of sd1's closed tree (counts, shortest arrivals,
cell ids, digests) as read on 2026-10-12. They are read back from the tree at the open and compared; they enter no selection, claim, rule or run module (a static test asserts it).
Nothing here writes under any earlier tree (a static test guards that). The five trees are only read.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_resume as rs  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd4_resume as r4  # noqa: E402
import m8_rd4_select as s4  # noqa: E402
import m8_sd1_resume as r5  # noqa: E402
import m8_sd1_rule as rule5  # noqa: E402
import m8_sd1_select as s5  # noqa: E402
import m8_sd2_artifacts as art  # noqa: E402
import m8_sd2_claims as cl6  # noqa: E402
import m8_sd2_select as s6  # noqa: E402

RESUME6_CONTRACT = "m8_sd2_resume_v1"
PREDECESSOR = "sd1"
SD1_INCREMENT_NAME = "2026-10-11_incr_m8_sd1"
SD1_INCREMENT_MANIFEST_SHA256 = "4a204dcb77cadcc8129ef9da9c879099dae665a77cc42e4ed9403c7719d30dbc"
RECORD_SOURCE6 = "sessions/sd1/verification/replays.jsonl: exact clear replay of candidate 901 (kind clear, iteration 15795) of sd1"
# the archive's best VERIFIED clear before sd2 (sd1 candidate 901, kind clear, iteration 15795; route runs/m8_rd_sd1/routes/T_clear_best): the selection's E7 and the rule read these numbers, pinned at the open
RECORD_REFERENCE6 = s6.record_reference_block(completion_input_tick=2086, completion_time_passed=2085, native_action_digest="a2a85903e704aab4819a4c6bb8e73d3b69fffdcdfce08a85f7e5d24f4a4a4e23",
                                              words=2086, cid=901, iteration=15795, kind="clear", session=PREDECESSOR, source=RECORD_SOURCE6)
SD1_RECORD_REFERENCE = r5.RECORD_REFERENCE          # the reference sd1 ran under (rd4's 2,315 / 2,314): sd1's session event must carry it, and sd1's part rebuilds under its bound
SD1_MARGIN = rule5.MARGIN                           # 24: the margin sd1 ran under (its session event must carry it)
SD1_SESSION_DIGEST = "eb08059242eef123cce478fe7cfa2d2fa916b360438f0c1407fe16799ade3d28"      # v4 at sd1's reference, as sd1's session event and approval recorded it (recomputed at the open)
# the inherited record facts (the archive's own structure, read from sd1's closed tree; no census threshold)
INHERITED_RECORD6: Dict[str, Any] = {
    "best_verified": dict(RECORD_REFERENCE6),
    "verified_clears": [{"cid": 901, "iteration": 15795, "kind": "clear", "completion_input_tick": 2086, "completion_time_passed": 2085, "native_action_digest": RECORD_REFERENCE6["native_action_digest"], "words": 2086}],
    "clear_event_candidates": 2, "clear_trajectories_registered": 1, "unverified_clear_trajectories": [],
    "inherited_descriptive": {"count": 3, "exact": 3, "inexact": 0, "ticks": 7013},                       # sd1's three descriptive replays of rd4's unverified trajectories, all exact
    "levels": {"0": {"cells": 1944, "min_L": 0}, "1": {"cells": 3312, "min_L": 26}, "2": {"cells": 3928, "min_L": 91}, "3": {"cells": 5235, "min_L": 152}, "4": {"cells": 5956, "min_L": 254},
               "5": {"cells": 5486, "min_L": 433}, "6": {"cells": 5188, "min_L": 931}, "7": {"cells": 5742, "min_L": 1237}, "8": {"cells": 3553, "min_L": 1776}, "9": {"cells": 3658, "min_L": 1897},
               "10": {"cells": 5, "min_L": 2086}},
    "level_10_L": [2086, 2315, 2324, 2326, 2348], "top_eligible_level": {"level": 9, "min_L": 1897, "min_cell": 30961},
    "left_floor_grounded": {"cells": 20, "min_L": 1850},
    "claim_facts": {"wall_top_cell_ids": [18318, 18767, 26944, 39911], "cells_left_of_boundary": 7016, "grounded_cells_on_left_floor": 20, "cells_with_a_left_target_broken": 7216, "max_level": 10},
    "pred_outcome": "PROGRESS", "pred_line_status": "SD2_PROPOSABLE_NEW_REFERENCE", "pred_session_counts": True, "rd5_permitted": True, "pred_flags": []}
SD1_FACTS: Dict[str, Any] = {
    "files": 130, "bytes": 211_061_918, "increment_manifest_sha256": SD1_INCREMENT_MANIFEST_SHA256, "cells": 44007, "bursts": 17554, "events": 35118, "checkpoint_seq": 57, "previous_checkpoint_seq": 56,
    "exploration_ticks": 6_000_000, "dispatch_iterations": (0, 17556), "contiguous": True, "first_rd2_iteration": 2175, "first_rd3_iteration": 6212, "first_rd4_iteration": 10406, "first_sd1_iteration": 13886,
    "first_sd2_iteration": 17557, "returns": 3671, "sd1_cells_created": 6695, "first_new_cell": 37312, "outcome": "PROGRESS", "line_status": "SD2_PROPOSABLE_NEW_REFERENCE", "session_counts": True,
    "sd1_record_reference": dict(SD1_RECORD_REFERENCE), "sd1_margin": 24, "sd1_session_digest": SD1_SESSION_DIGEST, "archive_created_utc": "2026-10-12T03:38:54Z",
    "close_record_sha256": "2d919ed9e695ddcb740ff8b49350b2b82b4b2b8bd2e6cc0a955b41652a2a1efa", "rule_record_sha256": "7988348007cede666eeb4b0777b038b9710bdf3cdb419207340e3e27292023f6",
    "verification_record_sha256": "e5c0f2ee0965fe2f9c78d38359bf72faa07e465dc538955dac8a416a76d989f1", "inherited_record": INHERITED_RECORD6}
# sd1's closing overlay under v4 at sd1's reference (its close record, `archive.overlay_close_v4`): the headline figures the open must reproduce exactly, and the digest of its rows
EXPECTED_SD1_CLOSE_OVERLAY_V4: Dict[str, Any] = {
    "cells": 44007, "eligible_v1": 35895, "descent_among_v1_eligible": 5727, "bound_among_v1_eligible": 4675, "union": 9514, "eligible_v2": 26381, "eligible_v3": 27841, "eligible_v4": 27603,
    "bound_L": 2290, "record_reference_completion_input_tick": 2315, "margin": 24, "record_bound_cells": 317, "record_bound_among_v3_eligible": 238,
    "record_bound_by_level": {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0, "8": 106, "9": 207, "10": 4},
    "record_bound_among_v3_eligible_by_level": {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0, "8": 44, "9": 194, "10": 0},
    "eligible_v4_by_level": {"0": 996, "1": 2457, "2": 2687, "3": 3493, "4": 3040, "5": 3238, "6": 2948, "7": 3820, "8": 1546, "9": 3378, "10": 0},
    "shortest_L_by_level": {"0": 0, "1": 26, "2": 91, "3": 152, "4": 254, "5": 433, "6": 931, "7": 1237, "8": 1776, "9": 1897, "10": 2086},
    "shortest_eligible_L_by_level": {"0": 0, "1": 26, "2": 91, "3": 152, "4": 254, "5": 433, "6": 931, "7": 1237, "8": 1776, "9": 1897, "10": None},
    "launch_capable_cells": 1248, "grounded_cells": 701, "step_contact_cells": 121, "still_eligible": {"launch_capable": 1199, "step_contact": 121, "grounded": 701}}
SD1_CLOSING_OVERLAY_V4_SHA256 = "f6af59157fb2b420c56aa8751bfe1dd94687a2d0069f2747697605554464bb29"     # as computed at the preparation (a test and the approval pin it)
# sd2's own open overlay under v4 at the new reference (E7 at L <= 2,061): the registered figures, computed at the preparation (a test and the approval pin them). E7 excludes 4,697 cells
# (63 at level 7, 1,992 at level 8, 2,637 at level 9, the 5 terminal level-10 cells), 3,242 of them eligible under v3: 27,841 v3-eligible cells become 24,599 v4-eligible ones.
EXPECTED_OPEN_OVERLAY6: Dict[str, Any] = {
    "cells": 44007, "eligible_v1": 35895, "descent_among_v1_eligible": 5727, "bound_among_v1_eligible": 4675, "union": 9514, "eligible_v2": 26381, "eligible_v3": 27841, "eligible_v4": 24599,
    "bound_L": 2061, "record_reference_completion_input_tick": 2086, "margin": 24, "record_bound_cells": 4697, "record_bound_among_v3_eligible": 3242,
    "record_bound_by_level": {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7": 63, "8": 1992, "9": 2637, "10": 5},
    "record_bound_among_v3_eligible_by_level": {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7": 24, "8": 650, "9": 2568, "10": 0},
    "eligible_v4_by_level": {"0": 996, "1": 2457, "2": 2687, "3": 3493, "4": 3040, "5": 3238, "6": 2948, "7": 3796, "8": 940, "9": 1004, "10": 0},
    "shortest_L_by_level": {"0": 0, "1": 26, "2": 91, "3": 152, "4": 254, "5": 433, "6": 931, "7": 1237, "8": 1776, "9": 1897, "10": 2086},
    "shortest_eligible_L_by_level": {"0": 0, "1": 26, "2": 91, "3": 152, "4": 254, "5": 433, "6": 931, "7": 1237, "8": 1776, "9": 1897, "10": None},
    "launch_capable_cells": 1248, "grounded_cells": 701, "step_contact_cells": 121, "still_eligible": {"launch_capable": 1199, "step_contact": 121, "grounded": 701}}
SD2_OPEN_OVERLAY_SHA256 = "2481c0d33abc5c025c67f9d59fcac6268b195a303ae5bb58d9a8f94ec73ad420"
record_fact_problems = r5.record_fact_problems      # generic: every difference between the facts read from a tree and the registered ones


class Resume6Error(RuntimeError):
    """The open protocol failed (the session is refused, nothing runs)."""


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# -- prior sessions' records (read, never assumed) ----------------------------------------------------------------------------------------------------


def prior_milestones6(rd1_dir: Path, rd2_dir: Path, rd3_dir: Path, rd4_dir: Path, sd1_dir: Path) -> Dict[str, Any]:
    out = dict(r5.prior_milestones5(rd1_dir, rd2_dir, rd3_dir, rd4_dir))
    p = Path(sd1_dir) / "sessions" / PREDECESSOR / "rule.json"
    if p.is_file():
        r = _read(p)
        b = r.get("best_verified") or {}
        out[PREDECESSOR] = {"outcome": r.get("outcome"), "best_completion_input_tick": b.get("completion_input_tick"), "line_status": (r.get("line") or {}).get("status"),
                            "source": f"sessions/{PREDECESSOR}/rule.json"}
    else:
        out[PREDECESSOR] = None
    return out


def sd1_line_status(sd1_dir: Path, session: str = PREDECESSOR) -> Dict[str, Any]:
    """sd1's recorded line status (its status, whether it counted, the rd line it copied through), read from its own rule record; a missing record is refused by the caller, never defaulted."""
    p = Path(sd1_dir) / "sessions" / session / "rule.json"
    if not p.is_file():
        return {"status": None, "session_counts": None, "rd5_permitted": None, "outcome": None, "source": None, "missing": True}
    r = _read(p)
    line = r.get("line") or {}
    rd = line.get("rd_line") or {}
    return {"status": line.get("status"), "session_counts": line.get("session_counts"), "rd5_permitted": rd.get(f"rd5_permitted_after_{session}"), "outcome": r.get("outcome"),
            "flags": list(r.get("flags") or []), "source": f"sessions/{session}/rule.json", "missing": False}


# -- the inherited record facts ---------------------------------------------------------------------------------------------------------------------------


def verified_clears_of6(pred_dir: Path, session: str = PREDECESSOR) -> List[Dict[str, Any]]:
    """Every exact clear replay of the predecessor's OWN candidates (its replays.jsonl without the header row and without its inherited descriptive replays), with both clocks and the digest of
    its registered words (the clear-kind twin of a `left`/`t` candidate shares its trajectory)."""
    tr = cl6.clear_trajectories6(pred_dir, session)
    words = cl6.registry_words(pred_dir, session)
    out: List[Dict[str, Any]] = []
    for r in cl6.predecessor_replays(pred_dir, session):
        if not (r.get("exact") and r.get("clear")):
            continue
        c = tr["candidates_by_cid"].get(int(r["cid"]))
        if c is None:
            raise Resume6Error(f"{session}'s replay of candidate {r['cid']} has no registry entry")
        w = words[int(c["cid"])]
        if c["kind"] == "t":
            w = w[:int(c["event_j"])]
        w = w[:int(r["counted"])]
        facts = r.get("clear_facts") or {}
        out.append({"cid": int(c["cid"]), "iteration": int(c["iteration"]), "kind": c["kind"], "completion_input_tick": int(facts["completion_input_tick"]),
                    "completion_time_passed": int(facts["completion_time_passed"]), "native_action_digest": mcell.words_digest(w), "words": len(w)})
    out.sort(key=lambda v: (v["completion_input_tick"], v["cid"]))
    return out


def record_reference_from6(pred_dir: Path, session: str = PREDECESSOR) -> Dict[str, Any]:
    """The archive's best verified clear, read from the predecessor's own records: the exact clear replay with the smallest completion_input_tick (then cid)."""
    vc = verified_clears_of6(pred_dir, session)
    if not vc:
        raise Resume6Error(f"{session} holds no exact clear replay: there is no record reference to search below")
    b = vc[0]
    return s6.record_reference_block(completion_input_tick=b["completion_input_tick"], completion_time_passed=b["completion_time_passed"], native_action_digest=b["native_action_digest"],
                                     words=b["words"], cid=b["cid"], iteration=b["iteration"], kind=b["kind"], session=session,
                                     source=f"sessions/{session}/verification/replays.jsonl: exact clear replay of candidate {b['cid']} (kind {b['kind']}, iteration {b['iteration']}) of {session}")


def inherited_record_facts6(pred_dir: Path, a: march.Archive, session: str = PREDECESSOR) -> Dict[str, Any]:
    """The archive's own structure and the predecessor's own records, as INHERITED_RECORD6 pins them."""
    pred_dir = Path(pred_dir)
    rr = record_reference_from6(pred_dir, session)
    tr = cl6.clear_trajectories6(pred_dir, session)
    levels = sorted({c.level for c in a.cells})
    top = max((c.level for c in a.cells if a.eligible(c)), default=0)
    top_cells = [c for c in a.cells if c.level == top and a.eligible(c)]
    short = min(top_cells, key=lambda c: (c.L, c.id)) if top_cells else None
    lf = [c for c in a.cells if c.key[2] == mcell.RES_GROUNDED and c.key[4] in mcell.LEFT_FLOOR_LINES]
    line = sd1_line_status(pred_dir, session)
    ver_p = pred_dir / "sessions" / session / "verification.json"
    inh_rec: Optional[Dict[str, Any]] = None
    if ver_p.is_file():
        inh = _read(ver_p).get("inherited_descriptive") or {}
        recs = inh.get("records") or []
        inh_rec = {"count": inh.get("count"), "exact": inh.get("exact"), "inexact": sum(1 for x in recs if not x.get("exact")), "ticks": inh.get("ticks")}
    return {"best_verified": rr, "verified_clears": verified_clears_of6(pred_dir, session),
            "clear_event_candidates": sum(1 for c in tr["candidates_by_cid"].values() if cl6.clear_tick(c) is not None), "clear_trajectories_registered": len(tr["jobs"]),
            "unverified_clear_trajectories": [{"iteration": j["iteration"], "first_clear": j["first_clear"]} for j in tr["jobs"] if not j["verified_by_predecessor"]],
            "inherited_descriptive": inh_rec,
            "levels": {str(lv): {"cells": sum(1 for c in a.cells if c.level == lv), "min_L": min(c.L for c in a.cells if c.level == lv)} for lv in levels},
            "level_10_L": sorted(c.L for c in a.cells if c.level == mcell.TARGETS_TOTAL),
            "top_eligible_level": {"level": top, "min_L": short.L if short else None, "min_cell": short.id if short else None},
            "left_floor_grounded": {"cells": len(lf), "min_L": min((c.L for c in lf), default=None)},
            "claim_facts": dict(r4.inherited_claim_facts(a)),
            "pred_outcome": line.get("outcome"), "pred_line_status": line.get("status"), "pred_session_counts": line.get("session_counts"), "rd5_permitted": line.get("rd5_permitted"),
            "pred_flags": line.get("flags")}


# -- R2 / R4: sd1's closing archive --------------------------------------------------------------------------------------------------------------------------


def sd1_archive_facts(rd1_dir: Path, rd2_dir: Path, rd3_dir: Path, rd4_dir: Path, sd1_dir: Path, lines_sha256: Optional[str] = None, expect: Optional[Mapping[str, Any]] = None, *,
                      with_audit: bool = True, keep_archive: bool = False) -> Dict[str, Any]:
    """Read and audit sd1's closing archive with sd2's code: manifest, checkpoints, close record, counts, the four session events and their digests (v4 at sd1's own reference), the
    iterations, the ledger audit, the prefix chain rd1 -> rd2 -> rd3 -> rd4 -> sd1, the inherited record facts, sd1's decision, line and record hashes. `expect` = the registered facts
    (SD1_FACTS; a parameter for the tests on synthetic trees only)."""
    E = dict(SD1_FACTS if expect is None else expect)
    rd1_dir, rd2_dir, rd3_dir, rd4_dir, sd1_dir = Path(rd1_dir), Path(rd2_dir), Path(rd3_dir), Path(rd4_dir), Path(sd1_dir)
    problems: List[str] = []
    best, meta, report = march.load_latest_verified(sd1_dir / "archive")
    seqs = {r["dir"]: r.get("checkpoint_seq") for r in report if r["state"] == "verified"}
    if best is None or meta is None:
        return {"ok": False, "problems": ["no verified checkpoint"], "checkpoints": report}
    if Path(best).name != "archive" or int(meta["checkpoint_seq"]) != E["checkpoint_seq"] or seqs.get("archive.prev") != E["previous_checkpoint_seq"]:
        problems.append(f"checkpoints {seqs} (best {Path(best).name}), expected {E['checkpoint_seq']} / {E['previous_checkpoint_seq']}")
    a, meta = s6.Archive6.read_dir(sd1_dir / "archive")
    if a.sd2_first_iteration is not None:
        problems.append("the predecessor's archive already carries an sd2 session event")
    lines = str(lines_sha256 if lines_sha256 is not None else (meta.get("pin_tick0") or {}).get("lines"))
    counts = (len(a.cells), len(a.bursts), len(a.events))
    if counts != (E["cells"], E["bursts"], E["events"]):
        problems.append(f"counts {counts}, expected {(E['cells'], E['bursts'], E['events'])}")
    sd = sd1_dir / "sessions" / PREDECESSOR
    close_p = sd / "close.json"
    close = _read(close_p) if close_p.is_file() else {}
    manifest = {n: march.sha256_file(sd1_dir / "archive" / n) for n in march.DATA_FILES}
    if (close.get("archive") or {}).get("manifest") != manifest:
        problems.append("the archive's files differ from sd1's close record")
    if (close.get("archive") or {}).get("checkpoint_seq") != E["checkpoint_seq"]:
        problems.append("the close record's checkpoint sequence differs")
    if "archive_created_utc" in E and (meta.get("created_utc") != E["archive_created_utc"] or (close.get("archive") or {}).get("created_utc") != E["archive_created_utc"]):
        problems.append(f"sd1's archive_meta created_utc {meta.get('created_utc')!r} differs from the registered {E['archive_created_utc']!r}")
    if not art.is_stamped(meta):
        problems.append("sd1's archive_meta.json carries no stamp")
    state_p = sd / "state.json"
    if not state_p.is_file() or _read(state_p).get("phase") != "done":
        problems.append("sd1's session state is not done")
    rule_p = sd / "rule.json"
    rule_rec = _read(rule_p) if rule_p.is_file() else {}
    line_rec = rule_rec.get("line") or {}
    if "outcome" in E and rule_rec.get("outcome") != E["outcome"]:
        problems.append(f"sd1's recorded decision {rule_rec.get('outcome')!r} differs from the registered {E['outcome']!r}")
    if "line_status" in E and (line_rec.get("status") != E["line_status"] or line_rec.get("session_counts") != E["session_counts"]):
        problems.append(f"sd1's recorded line {line_rec.get('status')!r} (counts {line_rec.get('session_counts')!r}) differs from the registered {E['line_status']!r} / {E['session_counts']!r}")
    for key, name in (("close_record_sha256", "close.json"), ("rule_record_sha256", "rule.json"), ("verification_record_sha256", "verification.json")):
        if key in E:
            p = sd / name
            got = rs.sha256_file(p) if p.is_file() else None
            if got != E[key]:
                problems.append(f"sd1's {name} sha256 {got} differs from the registered {E[key]}")
    lt = meta.get("ledger_T") or {}
    if "returns" in E and (lt.get("jobs") != E["returns"] or lt.get("ticks") != E["exploration_ticks"]):
        problems.append(f"sd1's ledger totals {lt} differ from the registered {E['returns']} returns / {E['exploration_ticks']} ticks")
    if "first_new_cell" in E and meta.get("first_new_cell") != E["first_new_cell"]:
        problems.append(f"sd1's first_new_cell {meta.get('first_new_cell')} differs from the registered {E['first_new_cell']}")
    if "sd1_cells_created" in E and len(a.cells) - int(meta.get("first_new_cell") or 0) != E["sd1_cells_created"]:
        problems.append(f"sd1 created {len(a.cells) - int(meta.get('first_new_cell') or 0)} cells, the registered figure is {E['sd1_cells_created']}")
    if meta.get("archive_id") != rs.RD1_ARCHIVE_ID or meta.get("schema") != s2.ARCHIVE_SCHEMA_V2 or meta.get("mode") != 2 or meta.get("select4_contract") != s5.SELECT4_CONTRACT \
            or meta.get("archive5_contract") != s5.ARCHIVE5_CONTRACT:
        problems.append("archive id, schema, mode or select contract differs")
    sess = [e for e in a.events if e["ev"] == "session"]
    v2_now = s2.select2_contract_digest(a.clf.table_sha256, lines, a.floor_min)
    v3_now = s4.select3_contract_digest(a.clf.table_sha256, lines, a.floor_min)
    v4_sd1_now: Optional[str] = None
    want_ev = [("rd2", E["first_rd2_iteration"]), ("rd3", E["first_rd3_iteration"]), ("rd4", E["first_rd4_iteration"]), (PREDECESSOR, E["first_sd1_iteration"])]
    if [(e.get("name"), int(e["first_iteration"])) for e in sess] != want_ev:
        problems.append(f"session events {[(e.get('name'), e.get('first_iteration')) for e in sess]}, expected {want_ev}")
    else:
        if sess[0]["digest"] != v2_now or sess[1]["digest"] != v2_now:
            problems.append("rd2's or rd3's session digest differs from the v2 digest recomputed from the current contract (they did not run v2 unchanged)")
        if sess[2]["digest"] != v3_now:
            problems.append("rd4's session digest differs from the v3 digest recomputed from the current contract (rd4 did not run v3 unchanged)")
        ev1 = sess[3]
        try:
            s6.validate_record_reference(ev1.get("record_reference"))
            v4_sd1_now = s6.select4_contract_digest(a.clf.table_sha256, lines, a.floor_min, ev1["record_reference"], int(ev1["margin"]))
            if ev1["digest"] != v4_sd1_now:
                problems.append("sd1's session digest differs from the v4 digest recomputed at sd1's own reference (sd1 did not run v4 unchanged)")
            if "sd1_record_reference" in E and json.dumps(ev1["record_reference"], sort_keys=True) != json.dumps(dict(E["sd1_record_reference"]), sort_keys=True):
                problems.append("sd1's session event carries a record reference other than the registered one (rd4's verified clear)")
            if "sd1_margin" in E and int(ev1["margin"]) != int(E["sd1_margin"]):
                problems.append(f"sd1's session event carries the margin {ev1['margin']}, the registered one is {E['sd1_margin']}")
            if "sd1_session_digest" in E and ev1["digest"] != E["sd1_session_digest"]:
                problems.append(f"sd1's session digest {ev1['digest']} differs from the registered {E['sd1_session_digest']}")
        except (s5.Select5Error, KeyError, TypeError, ValueError) as exc:
            problems.append(f"sd1's session event is malformed: {type(exc).__name__}: {exc}")
    its = sorted(e["it"] for e in a.events if e["ev"] == "dispatch")
    if E.get("contiguous", True):
        if its != list(range(E["dispatch_iterations"][0], E["dispatch_iterations"][1] + 1)):
            problems.append(f"the dispatch iterations are not the contiguous {E['dispatch_iterations'][0]}..{E['dispatch_iterations'][1]}")
    elif not its or its != sorted(set(its)) or (its[0], its[-1]) != tuple(E["dispatch_iterations"]):
        problems.append(f"the dispatch iterations are not strictly increasing from {E['dispatch_iterations'][0]} to {E['dispatch_iterations'][1]}")
    if "first_sd2_iteration" in E and its and its[-1] + 1 != E["first_sd2_iteration"]:
        problems.append(f"the first sd2 iteration would be {its[-1] + 1}, the registered one is {E['first_sd2_iteration']}")
    if any(e["ev"] == "fail" for e in a.events):
        problems.append("the ledger holds fail events")
    d_close = close.get("archive", {}).get("diag2") or {}
    cur = {k: (len(v) if isinstance(v, list) else v) for k, v in a.diag2.items()}
    if cur != d_close:
        problems.append(f"the diag2 counters {cur} differ from sd1's close record {d_close}")
    base_ok = True
    for n in (*march.DATA_FILES, march.MANIFEST):
        pa, pb = sd1_dir / "base" / n, rd4_dir / "archive" / n
        if not (pa.is_file() and pb.is_file() and march.sha256_file(pa) == march.sha256_file(pb)):
            base_ok = False
    if not base_ok:
        problems.append("sd1's base copy differs from rd4's closing archive files")
    chain = r5.prefix_chain(rd1_dir / "archive", rd2_dir / "archive", rd3_dir / "archive", rd4_dir / "archive", sd1_dir / "archive")
    if not chain["ok"]:
        problems += [f"prefix chain: {p}" for p in chain["problems"]]
    try:
        inh = inherited_record_facts6(sd1_dir, a)
        rr = inh["best_verified"]
    except (Resume6Error, ValueError, KeyError, OSError) as exc:
        inh, rr = {}, None
        problems.append(f"the inherited record facts could not be read: {type(exc).__name__}: {exc}")
    if inh and "inherited_record" in E:
        problems += record_fact_problems(inh, E["inherited_record"])
    if rr is not None and rr["completion_input_tick"] != rr["words"]:
        problems.append("the record reference's clock differs from its word count")
    line = sd1_line_status(sd1_dir)
    if line.get("missing"):
        problems.append("sd1's rule record (the sd line status) is missing")
    aud: Dict[str, Any] = {"skipped": True}
    if with_audit:
        aud = s6.audit6(a, lines)
        if not aud["ok"]:
            problems += [f"sd1 audit: {p}" for p in aud["problems"][:5]]
    return {"ok": not problems, "problems": problems, "checkpoints": seqs, "counts": {"cells": counts[0], "bursts": counts[1], "events": counts[2]}, "manifest": manifest,
            "close_record_sha256": rs.sha256_file(close_p) if close_p.is_file() else None, "audit": aud, "session_events": sess,
            "digest_recomputed": {"v2": v2_now, "v3": v3_now, "v4_sd1": v4_sd1_now}, "dispatch_iterations": [its[0], its[-1]] if its else None, "diag2": cur, "prefix_chain": chain,
            "pin_tick0": meta.get("pin_tick0"), "pins": meta.get("pins"), "ticks": meta.get("ticks"), "ledger_T": meta.get("ledger_T"), "sd1_checkpoint_seq": int(meta["checkpoint_seq"]),
            "first_sd2_iteration": (its[-1] + 1) if its else 0, "lines_sha256": lines, "inherited_record": inh, "record_reference": rr, "sd1_line": line,
            "sd1_session_event": sess[3] if len(sess) == 4 else None, "archive_created_utc": meta.get("created_utc"), "archive": a if keep_archive else None}


# -- R5: the two overlays ---------------------------------------------------------------------------------------------------------------------------------------


def build_overlay6(archive_dir: Path, previous_reference: Mapping[str, Any], previous_margin: int, record_reference: Mapping[str, Any], margin: int, floor_min: Optional[float] = None) -> Dict[str, Any]:
    """sd1's closing overlay under v4 at sd1's reference (reproduced) and sd2's open overlay under v4 at the new reference, each computed twice (the incremental structures of one load and
    the first-principles recomputation of another) and required equal, with their bytes, digests and counts."""
    t_prev, t_new = int(previous_reference["completion_input_tick"]), int(record_reference["completion_input_tick"])
    a, _m = s6.Archive6.read_dir(Path(archive_dir), floor_min=floor_min)
    b, _m2 = s6.Archive6.read_dir(Path(archive_dir), floor_min=floor_min)
    desc, bound = b.reference_flags()
    rows_p_a, rows_p_b = s6.overlay_rows6(a, t_prev, previous_margin), s6.overlay_rows6(b, t_prev, previous_margin, desc, bound)
    rows_n_a, rows_n_b = s6.overlay_rows6(a, t_new, margin), s6.overlay_rows6(b, t_new, margin, desc, bound)
    bpa, bpb = s6.overlay_bytes6(rows_p_a), s6.overlay_bytes6(rows_p_b)
    bna, bnb = s6.overlay_bytes6(rows_n_a), s6.overlay_bytes6(rows_n_b)
    problems: List[str] = []
    if bpa != bpb:
        problems.append("sd1's closing overlay computed twice differs")
    if bna != bnb:
        problems.append("sd2's open overlay computed twice differs")
    return {"ok": not problems, "problems": problems,
            "sd1_closing": {"rows": rows_p_a, "bytes": bpa, "sha256": hashlib.sha256(bpa).hexdigest(), "counts": s6.overlay_counts6(a, rows_p_a, t_prev, previous_margin)},
            "v4": {"rows": rows_n_a, "bytes": bna, "sha256": hashlib.sha256(bna).hexdigest(), "counts": s6.overlay_counts6(a, rows_n_a, t_new, margin)},
            "record_reference": dict(record_reference), "margin": int(margin), "previous_record_reference": dict(previous_reference), "previous_margin": int(previous_margin)}


def closing_overlay6(sd1_dir: Path, previous_reference: Mapping[str, Any], previous_margin: int, record_reference: Mapping[str, Any], margin: int, expect_sd1: Optional[Mapping[str, Any]] = None,
                     expect_v4: Optional[Mapping[str, Any]] = None, floor_min: Optional[float] = None, *, sd1_sha256: Optional[str] = None, v4_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Both overlays of sd1's closing archive, compared with the overlay counts sd1's close record stores (`overlay_close_v4`, in full), the registered headline figures and (when given) the
    pinned digests."""
    sd1_dir = Path(sd1_dir)
    ov = build_overlay6(sd1_dir / "archive", previous_reference, previous_margin, record_reference, margin, floor_min)
    problems = list(ov["problems"])
    close_p = sd1_dir / "sessions" / PREDECESSOR / "close.json"
    stored = (_read(close_p).get("archive") or {}).get("overlay_close_v4") if close_p.is_file() else None
    if stored is None:
        problems.append("sd1's close record holds no closing overlay under v4")
    elif json.dumps(ov["sd1_closing"]["counts"], sort_keys=True) != json.dumps(stored, sort_keys=True):
        problems.append("sd1's closing overlay counts differ from sd1's close record")
    for k, v in (EXPECTED_SD1_CLOSE_OVERLAY_V4 if expect_sd1 is None else expect_sd1).items():
        if json.dumps(ov["sd1_closing"]["counts"].get(k), sort_keys=True) != json.dumps(v, sort_keys=True):
            problems.append(f"sd1 closing overlay {k}: {ov['sd1_closing']['counts'].get(k)} (registered {v})")
    for k, v in (EXPECTED_OPEN_OVERLAY6 if expect_v4 is None else expect_v4).items():
        if json.dumps(ov["v4"]["counts"].get(k), sort_keys=True) != json.dumps(v, sort_keys=True):
            problems.append(f"sd2 open overlay {k}: {ov['v4']['counts'].get(k)} (registered {v})")
    if sd1_sha256 is not None and ov["sd1_closing"]["sha256"] != sd1_sha256:
        problems.append(f"sd1's closing overlay sha256 {ov['sd1_closing']['sha256']} differs from the registered {sd1_sha256}")
    if v4_sha256 is not None and ov["v4"]["sha256"] != v4_sha256:
        problems.append(f"sd2's open overlay sha256 {ov['v4']['sha256']} differs from the registered {v4_sha256}")
    return dict(ov, ok=not problems, problems=problems, stored_close_counts=stored)


# -- R6: materialise ---------------------------------------------------------------------------------------------------------------------------------------------


def materialise6(sd1_dir: Path, new_root: Path, *, facts: Mapping[str, Any], overlay: Mapping[str, Any], lines_sha256: str, meta_extra: Mapping[str, Any], increment_manifest_sha256: str,
                 utc: str, margin: int, record_reference: Mapping[str, Any], floor_min: Optional[float] = None) -> s6.Archive6:
    """Create sd2's tree: base/ (sd1's closing data files and manifest, byte for byte), derived/ (both overlays, their stamped companion record, the stamped base record) and the first sd2
    checkpoint in archive/ (sd1's cells and ledger plus sd2's `session` event), whose archive_meta.json carries the stamp with created_utc = `utc`, fixed here for every later checkpoint.
    Returns the archive (mode 2, sd2 begun)."""
    sd1_dir, new_root = Path(sd1_dir), Path(new_root)
    if new_root.exists():
        raise Resume6Error(f"{new_root} exists (never overwritten)")
    rr = dict(record_reference)
    s6.validate_record_reference(rr)
    if facts.get("record_reference") is not None and json.dumps(dict(facts["record_reference"]), sort_keys=True) != json.dumps(rr, sort_keys=True):
        raise Resume6Error("the record reference to materialise differs from the one read from the predecessor's records")
    (new_root / "base").mkdir(parents=True)
    (new_root / "derived").mkdir()
    base_hashes: Dict[str, str] = {}
    for n in (*march.DATA_FILES, march.MANIFEST):
        src, dst = sd1_dir / "archive" / n, new_root / "base" / n
        shutil.copyfile(src, dst)
        base_hashes[n] = rs.sha256_file(dst)
        if base_hashes[n] != rs.sha256_file(src):
            raise Resume6Error(f"the base copy of {n} differs from sd1's file")
    if march.verify_manifest(new_root / "base"):
        raise Resume6Error("the base copy's manifest does not verify")
    a, _meta = s6.Archive6.read_dir(new_root / "base", floor_min=floor_min)
    for name, part in (("sd1_closing_overlay.jsonl", overlay["sd1_closing"]), ("open_overlay.jsonl", overlay["v4"])):
        p = new_root / "derived" / name
        p.write_bytes(part["bytes"])
        if hashlib.sha256(p.read_bytes()).hexdigest() != part["sha256"]:
            raise Resume6Error(f"the stored overlay {name} differs from its digest")
    art.write_json5(new_root / "derived" / "open_overlay.json", {
        "kind": "sd2's open overlay under m8_rd_select_v4 at the new record reference (E7 applied) and sd1's closing overlay under m8_rd_select_v4 at sd1's reference (reproduced), both of sd1's closing archive, each computed twice and equal",
        "open_overlay": {"file": "open_overlay.jsonl", "sha256": overlay["v4"]["sha256"], "counts": overlay["v4"]["counts"], "rows": len(overlay["v4"]["rows"])},
        "sd1_closing_overlay": {"file": "sd1_closing_overlay.jsonl", "sha256": overlay["sd1_closing"]["sha256"], "counts": overlay["sd1_closing"]["counts"], "rows": len(overlay["sd1_closing"]["rows"])},
        "record_reference": rr, "margin": int(margin), "previous_record_reference": dict(overlay["previous_record_reference"]), "previous_margin": int(overlay["previous_margin"]),
        "utc": utc, "computed_twice_equal": True}, created_utc=utc)
    ev = a.begin_sd2(int(facts["first_sd2_iteration"]), lines_sha256, rr, int(margin))
    base = {"schema": "m8_sd2_base_v1", "sd1_checkpoint_seq": facts.get("sd1_checkpoint_seq"), "sd1_archive_files_sha256": dict(base_hashes), "sd1_close_record_sha256": facts.get("close_record_sha256"),
            "sd1_manifest": facts.get("manifest"), "sd1_increment": SD1_INCREMENT_NAME, "sd1_increment_manifest_sha256": increment_manifest_sha256, "session_event": ev,
            "open_overlay_sha256": overlay["v4"]["sha256"], "sd1_closing_overlay_sha256": overlay["sd1_closing"]["sha256"], "inherited_record": facts.get("inherited_record"),
            "sd1_line": facts.get("sd1_line"), "sd1_session_event": facts.get("sd1_session_event"), "previous_record_reference": dict(overlay["previous_record_reference"]), "utc": utc}
    art.write_json5(new_root / "derived" / "base.json", base, created_utc=utc)
    meta = art.stamp(dict(meta_extra, checkpoint_seq=int(facts["sd1_checkpoint_seq"]) + 1, why="open", utc=utc, session=s6.SESSION_NAME, base=base), created_utc=utc)
    march.save_checkpoint(new_root / "archive", a, meta)
    pp = rs.prefix_property(sd1_dir / "archive", new_root / "archive")                    # sd2's ledger begins with sd1's exact bytes, from the first checkpoint on
    if not pp["ok"]:
        raise Resume6Error(f"sd2's first checkpoint does not begin with sd1's closing bytes: {pp['problems']}")
    written = _read(new_root / "archive" / "archive_meta.json")
    if written.get("created_utc") != utc or not art.is_stamped(written):
        raise Resume6Error("the materialised archive_meta.json is not stamped with the materialisation time")
    return a


# -- close: the prefix chain ------------------------------------------------------------------------------------------------------------------------------------


def prefix_chain6(rd1_archive: Path, rd2_archive: Path, rd3_archive: Path, rd4_archive: Path, sd1_archive: Path, sd2_archive: Path) -> Dict[str, Any]:
    """rd2's archive files begin with rd1's bytes, rd3's with rd2's closing bytes, rd4's with rd3's, sd1's with rd4's and sd2's with sd1's (every ledger line, burst index row and word)."""
    five = r5.prefix_chain(Path(rd1_archive), Path(rd2_archive), Path(rd3_archive), Path(rd4_archive), Path(sd1_archive))
    d = rs.prefix_property(Path(sd1_archive), Path(sd2_archive))
    return {"rd1_rd2": five["rd1_rd2"], "rd2_rd3": five["rd2_rd3"], "rd3_rd4": five["rd3_rd4"], "rd4_sd1": five["rd4_sd1"], "sd1_sd2": d, "ok": bool(five["ok"] and d["ok"]),
            "problems": list(five["problems"]) + [f"sd1->sd2: {p}" for p in d["problems"]]}
