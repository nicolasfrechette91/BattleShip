"""M8-rd4 resume: the open protocol of the third continuation, three levels deep (zero native ticks), and the close checks.

rd2's and rd3's protocols (rl/m8_rd_resume.py, rl/m8_rd3_resume.py, both unchanged and reused wherever generic) resumed the closed trees of rd1 and of rd2. rd4 resumes rd3's closed tree,
which continues rd2's, which continues rd1's:

    R1  immutability of ALL THREE earlier trees: runs/m8_rd/, runs/m8_rd_rd2/ and runs/m8_rd_rd3/ each hold exactly the files of their D: increment (paths, sizes, mtimes, sha256, and the
        backup's own bytes), each increment's record says PASS
    R2  rd1's and rd2's archive facts (their own audits) and rd3's closing archive facts: manifest verified, checkpoint 32 / previous 31, the five files equal rd3's close record, the
        counts (26,371 cells, 10,406 bursts, 20,814 events), the dispatch iterations 0..10,405 contiguous, no `fail` event, exactly two `session` events (rd2, rd3) whose digests equal the
        digest RECOMPUTED from the current v2 selection contract (the earlier sessions ran v2 unchanged), the diag2 counters equal rd3's close record, rd3's recorded decision, and the
        registered CLAIM PRECONDITIONS of the inherited archive (no grounded tick on the left floor, no left target broken in any inherited cell: every milestone above the wall top that
        an rd4 replay credits therefore arises in an rd4 burst)
    R3  the pins equal the archive's (executable, runtime files, frozen configuration, flags, contract digests including m8_rd_select_v2; v3 is rd4's own)
    R4  the ledger rebuild of rd3's closing archive (rd3's own `audit3`: rd1 part under v1, rd2 and rd3 parts under v2, zero ticks) and the prefix properties rd1 -> rd2 -> rd3
    R5  the closing v2 overlay of rd3's archive, computed twice (incremental and first-principles) and equal, with its digest, equal to the overlay counts rd3's close record stores
        (26,371 cells, 22,336 v1-eligible, 3,734 descent, 2,666 bound, 5,726 union, 16,610 eligible). Eligibility is unchanged under v3, so this IS the overlay at rd4's open
    R6  materialise runs/m8_rd_rd4/: rd3's five closing data files and manifest copied byte for byte into base/ (hashes equal), the overlay, a base record, rd4's `session` event (v3) and
        the first rd4 checkpoint (sequence 33)

Nothing here writes under runs/m8_rd/, runs/m8_rd_rd2/ or runs/m8_rd_rd3/ (a static test guards that). The three trees are only read.
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
import m8_rd3_resume as r3  # noqa: E402
import m8_rd3_select as s3  # noqa: E402
import m8_rd4_select as s4  # noqa: E402

RESUME4_CONTRACT = "m8_rd4_resume_v1"
RD3_INCREMENT_NAME = "2026-10-02_incr_m8_rd3"
RD3_INCREMENT_MANIFEST_SHA256 = "b6e13ecbc1ef9a76fee105de90fbf09072ae2b450f9f626542f6df355e35f324"
INHERITED_FACTS = {"wall_top_cell_ids": [18318, 18767], "cells_left_of_boundary": 54, "grounded_cells_on_left_floor": 0, "cells_with_a_left_target_broken": 0, "max_level": 7}
RD3_FACTS = {"files": 77, "bytes": 114_026_700, "increment_manifest_sha256": RD3_INCREMENT_MANIFEST_SHA256, "cells": 26371, "bursts": 10406, "events": 20814, "checkpoint_seq": 32,
             "previous_checkpoint_seq": 31, "exploration_ticks": 5_170_886, "dispatch_iterations": (0, 10405), "first_rd2_iteration": 2175, "first_rd3_iteration": 6212,
             "first_rd4_iteration": 10406, "returns": 4194, "rd3_cells_created": 7309, "outcome": "NO_NEW_MILESTONE", "m": 0, "inherited": INHERITED_FACTS}
# the closing overlay of rd3's archive (its close record, `archive.overlay_close`): the headline figures the open must reproduce exactly
EXPECTED_CLOSE_OVERLAY = {"cells": 26371, "eligible_v1": 22336, "descent_among_v1_eligible": 3734, "bound_among_v1_eligible": 2666, "union": 5726, "eligible_v2": 16610,
                          "launch_capable_cells": 614, "grounded_cells": 522, "step_contact_cells": 84,
                          "still_eligible": {"launch_capable": 572, "step_contact": 84, "grounded": 522}}
CLOSING_OVERLAY_SHA256 = "4ab51e43cf68aeceff126bce320735bced182bddd3a952f713daefb2ec664547"     # as computed at the preparation (a test and the approval pin it)


class Resume4Error(RuntimeError):
    """The open protocol failed (the session is refused, nothing runs)."""


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# -- prior sessions' recorded milestones (the budget status reads them, never assumes them) -------------------------------------------------------


def prior_milestones(rd1_dir: Path, rd2_dir: Path, rd3_dir: Path) -> Dict[str, Any]:
    """The milestone each earlier session recorded, read from its own files: rd1 and rd2 as rd3's protocol reads them, and rd3 (`sessions/rd3/rule.json`). A missing record is None and a
    record that lacks its milestone field raises (never read as zero)."""
    out = dict(r3.prior_milestones(rd1_dir, rd2_dir))
    p3 = Path(rd3_dir) / "sessions" / "rd3" / "rule.json"
    if p3.is_file():
        r = _read(p3)
        out["rd3"] = {"m": int(r["m"]), "milestone": r.get("highest_milestone", r.get("milestone")), "outcome": r.get("outcome"), "source": "sessions/rd3/rule.json"}
    else:
        out["rd3"] = None
    return out


# -- the claim preconditions of an inherited archive -----------------------------------------------------------------------------------------


def inherited_claim_facts(a: march.Archive) -> Dict[str, Any]:
    """What the inherited archive already holds of the milestone ladder above the wall top, and the frontier cells rd4 starts from. Zero grounded cells on the left floor and zero cells
    with a left target broken are what makes 'a crossing / left target / clear credited by an rd4 replay arises in an rd4 burst' true."""
    left_x = mcell.LEFT_BOUNDARY_X
    wall_top = [c.id for c in a.cells if c.key[2] == mcell.RES_GROUNDED and c.key[4] == mcell.L0_FLOOR_LINE]
    return {"wall_top_cell_ids": wall_top, "cells_left_of_boundary": sum(1 for c in a.cells if float(c.end[mcell.I_X]) < left_x),
            "grounded_cells_on_left_floor": sum(1 for c in a.cells if c.key[2] == mcell.RES_GROUNDED and c.key[4] in mcell.LEFT_FLOOR_LINES),
            "cells_with_a_left_target_broken": sum(1 for c in a.cells if any(not (c.key[3] >> i) & 1 for i in mcell.LEFT_TARGET_IDS)),
            "max_level": max((c.level for c in a.cells), default=0)}


def claim_precondition_problems(facts: Mapping[str, Any]) -> List[str]:
    out = []
    if facts["grounded_cells_on_left_floor"]:
        out.append(f"{facts['grounded_cells_on_left_floor']} inherited cells stand on the left floor: a crossing credited by an rd4 replay might not arise in an rd4 burst")
    if facts["cells_with_a_left_target_broken"]:
        out.append(f"{facts['cells_with_a_left_target_broken']} inherited cells have a left target broken")
    if facts["max_level"] >= 8:
        out.append(f"an inherited cell is at level {facts['max_level']} (a left target broken)")
    return out


def registry_milestone_events(rd1_dir: Path, rd2_dir: Path, rd3_dir: Path) -> Dict[str, Any]:
    """The first-event labels the three earlier sessions' arm-T candidate registries carry (`sessions/<rd>/ledger_T.json`, `candidates[*].first`): how many candidates carry a landing on the
    left floor (`left_floor`), a left-target break (`left_break`) or a clear. The cell-based facts above cannot see a grounded tick under an X-class status (that key has no floor); the
    registry can. A missing registry is None (refused)."""
    out: Dict[str, Any] = {}
    for name, root in (("rd1", rd1_dir), ("rd2", rd2_dir), ("rd3", rd3_dir)):
        p = Path(root) / "sessions" / name / "ledger_T.json"
        if not p.is_file():
            out[name] = None
            continue
        n = {"left_floor": 0, "left_break": 0, "clear": 0, "candidates": 0}
        for c in _read(p).get("candidates", []):
            n["candidates"] += 1
            first = c.get("first") or {}
            for k in ("left_floor", "left_break", "clear"):
                if first.get(k) is not None:
                    n[k] += 1
        out[name] = n
    return out


def registry_precondition_problems(facts: Mapping[str, Any]) -> List[str]:
    out = []
    for name, n in facts.items():
        if n is None:
            out.append(f"{name}'s candidate registry (sessions/{name}/ledger_T.json) is missing: the claim preconditions cannot be read")
        elif n["left_floor"] or n["left_break"] or n["clear"]:
            out.append(f"{name}'s registry holds {n['left_floor']} left-floor landings, {n['left_break']} left-target breaks and {n['clear']} clears: a credited milestone might not arise in an rd4 burst")
    return out


# -- R2 / R4: rd3's closing archive ---------------------------------------------------------------------------------------------------------------


def rd3_archive_facts(rd1_dir: Path, rd2_dir: Path, rd3_dir: Path, lines_sha256: Optional[str] = None, expect: Optional[Mapping[str, Any]] = None, *,
                      with_audit: bool = True, keep_archive: bool = False) -> Dict[str, Any]:
    """Read and audit rd3's closing archive with rd3's own code: manifest, checkpoints, close record, counts, the two session events and their digests, the iterations, the ledger audit,
    the prefix properties rd1 -> rd2 -> rd3 and the claim preconditions. `expect` = the registered facts (RD3_FACTS; a parameter for the tests on synthetic trees only)."""
    E = dict(RD3_FACTS if expect is None else expect)
    rd1_dir, rd2_dir, rd3_dir = Path(rd1_dir), Path(rd2_dir), Path(rd3_dir)
    problems: List[str] = []
    best, meta, report = march.load_latest_verified(rd3_dir / "archive")
    seqs = {r["dir"]: r.get("checkpoint_seq") for r in report if r["state"] == "verified"}
    if best is None or meta is None:
        return {"ok": False, "problems": ["no verified checkpoint"], "checkpoints": report}
    if Path(best).name != "archive" or int(meta["checkpoint_seq"]) != E["checkpoint_seq"] or seqs.get("archive.prev") != E["previous_checkpoint_seq"]:
        problems.append(f"checkpoints {seqs} (best {Path(best).name}), expected {E['checkpoint_seq']} / {E['previous_checkpoint_seq']}")
    a, meta = s4.Archive4.read_dir(rd3_dir / "archive")
    lines = str(lines_sha256 if lines_sha256 is not None else (meta.get("pin_tick0") or {}).get("lines"))
    counts = (len(a.cells), len(a.bursts), len(a.events))
    if counts != (E["cells"], E["bursts"], E["events"]):
        problems.append(f"counts {counts}, expected {(E['cells'], E['bursts'], E['events'])}")
    close_p = rd3_dir / "sessions" / "rd3" / "close.json"
    close = _read(close_p) if close_p.is_file() else {}
    manifest = {n: march.sha256_file(rd3_dir / "archive" / n) for n in march.DATA_FILES}
    if (close.get("archive") or {}).get("manifest") != manifest:
        problems.append("the archive's files differ from rd3's close record")
    if (close.get("archive") or {}).get("checkpoint_seq") != E["checkpoint_seq"]:
        problems.append("the close record's checkpoint sequence differs")
    state_p = rd3_dir / "sessions" / "rd3" / "state.json"
    if not state_p.is_file() or _read(state_p).get("phase") != "done":
        problems.append("rd3's session state is not done")
    rule_p = rd3_dir / "sessions" / "rd3" / "rule.json"
    rule_rec = _read(rule_p) if rule_p.is_file() else {}
    if "outcome" in E and (rule_rec.get("outcome") != E["outcome"] or rule_rec.get("m") != E["m"]):
        problems.append(f"rd3's recorded decision {rule_rec.get('outcome')!r} m={rule_rec.get('m')!r} differs from the registered {E['outcome']!r} m={E['m']!r}")
    lt = meta.get("ledger_T") or {}
    if "returns" in E and (lt.get("jobs") != E["returns"] or lt.get("ticks") != E["exploration_ticks"]):
        problems.append(f"rd3's ledger totals {lt} differ from the registered {E['returns']} returns / {E['exploration_ticks']} ticks")
    if meta.get("archive_id") != rs.RD1_ARCHIVE_ID or meta.get("schema") != s2.ARCHIVE_SCHEMA_V2 or meta.get("mode") != 2 or meta.get("select2_contract") != s2.SELECT2_CONTRACT:
        problems.append("archive id, schema, mode or select contract differs")
    sess = [e for e in a.events if e["ev"] == "session"]
    digest_now = s2.select2_contract_digest(a.clf.table_sha256, lines, a.floor_min)
    if [(e.get("name"), int(e["first_iteration"])) for e in sess] != [("rd2", E["first_rd2_iteration"]), ("rd3", E["first_rd3_iteration"])]:
        problems.append(f"session events {[(e.get('name'), e.get('first_iteration')) for e in sess]}, expected rd2 at {E['first_rd2_iteration']} and rd3 at {E['first_rd3_iteration']}")
    elif any(e["digest"] != digest_now for e in sess):
        problems.append("a session digest differs from the digest recomputed from the current v2 selection contract (rd2 and rd3 did not run v2 unchanged)")
    its = sorted(e["it"] for e in a.events if e["ev"] == "dispatch")
    if its != list(range(E["dispatch_iterations"][0], E["dispatch_iterations"][1] + 1)):
        problems.append(f"the dispatch iterations are not the contiguous {E['dispatch_iterations'][0]}..{E['dispatch_iterations'][1]}")
    if any(e["ev"] == "fail" for e in a.events):
        problems.append("the ledger holds fail events")
    d3 = close.get("archive", {}).get("diag2") or {}
    cur = {k: (len(v) if isinstance(v, list) else v) for k, v in a.diag2.items()}
    if cur != d3:
        problems.append(f"the diag2 counters {cur} differ from rd3's close record {d3}")
    base_ok = True
    for n in (*march.DATA_FILES, march.MANIFEST):
        pa, pb = rd3_dir / "base" / n, rd2_dir / "archive" / n
        if not (pa.is_file() and pb.is_file() and march.sha256_file(pa) == march.sha256_file(pb)):
            base_ok = False
    if not base_ok:
        problems.append("rd3's base copy differs from rd2's closing archive files")
    chain = prefix_chain3(rd1_dir / "archive", rd2_dir / "archive", rd3_dir / "archive")
    if not chain["ok"]:
        problems += [f"prefix chain: {p}" for p in chain["problems"]]
    inh = inherited_claim_facts(a)
    if "inherited" in E:
        if json.dumps(inh, sort_keys=True) != json.dumps(E["inherited"], sort_keys=True):
            problems.append(f"the inherited claim facts {inh} differ from the registered {E['inherited']}")
    problems += claim_precondition_problems(inh)
    reg = registry_milestone_events(rd1_dir, rd2_dir, rd3_dir)
    problems += registry_precondition_problems(reg)
    aud: Dict[str, Any] = {"skipped": True}
    if with_audit:
        aud = s3.audit3(a, lines)
        if not aud["ok"]:
            problems += [f"rd3 audit: {p}" for p in aud["problems"][:5]]
    return {"ok": not problems, "problems": problems, "checkpoints": seqs, "counts": {"cells": counts[0], "bursts": counts[1], "events": counts[2]}, "manifest": manifest,
            "close_record_sha256": rs.sha256_file(close_p) if close_p.is_file() else None, "audit": aud, "session_events": sess, "digest_recomputed": digest_now,
            "dispatch_iterations": [its[0], its[-1]] if its else None, "diag2": cur, "prefix_chain": chain, "pin_tick0": meta.get("pin_tick0"), "pins": meta.get("pins"),
            "ticks": meta.get("ticks"), "ledger_T": meta.get("ledger_T"), "rd3_checkpoint_seq": int(meta["checkpoint_seq"]), "first_rd4_iteration": (its[-1] + 1) if its else 0,
            "lines_sha256": lines, "inherited": inh, "registry_events": reg, "archive": a if keep_archive else None}


def prefix_chain3(rd1_archive: Path, rd2_archive: Path, rd3_archive: Path) -> Dict[str, Any]:
    return r3.prefix_chain(rd1_archive, rd2_archive, rd3_archive)


# -- R5: the closing overlay -------------------------------------------------------------------------------------------------------------------------


def closing_overlay(rd3_dir: Path, expect: Optional[Mapping[str, Any]] = None, floor_min: Optional[float] = None) -> Dict[str, Any]:
    """The v2 flags of every cell of rd3's closing archive, computed twice (the incremental structures of one load and the first-principles recomputation of another, required equal), with
    the bytes and their sha256, compared with the overlay counts rd3's close record stores and with the registered headline figures (`expect`). Eligibility is unchanged under v3."""
    rd3_dir = Path(rd3_dir)
    ov = rs.build_overlay(rd3_dir / "archive", floor_min)
    problems = list(ov["problems"])
    close_p = rd3_dir / "sessions" / "rd3" / "close.json"
    stored = (_read(close_p).get("archive") or {}).get("overlay_close") if close_p.is_file() else None
    if stored is None:
        problems.append("rd3's close record holds no closing overlay")
    elif json.dumps(ov["counts"], sort_keys=True) != json.dumps(stored, sort_keys=True):
        problems.append("the closing overlay counts differ from rd3's close record")
    want = EXPECTED_CLOSE_OVERLAY if expect is None else expect
    for k, v in want.items():
        if json.dumps(ov["counts"].get(k), sort_keys=True) != json.dumps(v, sort_keys=True):
            problems.append(f"overlay {k}: {ov['counts'].get(k)} (registered {v})")
    out = dict(ov, ok=not problems, problems=problems, stored_close_counts=stored)
    out.pop("archive", None)                        # the loaded archive is not kept (memory): the rows, the bytes and the counts are the record
    return out


# -- R6: materialise ----------------------------------------------------------------------------------------------------------------------------------


def materialise4(rd3_dir: Path, new_root: Path, *, facts: Mapping[str, Any], overlay: Mapping[str, Any], lines_sha256: str, meta_extra: Mapping[str, Any],
                 increment_manifest_sha256: str, utc: str, floor_min: Optional[float] = None) -> s4.Archive4:
    """Create rd4's tree: base/ (rd3's closing data files and manifest, byte for byte), derived/ (the closing overlay of rd3 = the overlay at the open, its digest, the base record) and the
    first rd4 checkpoint in archive/ (rd3's cells and ledger plus rd4's `session` event). Returns the archive (mode 2, rd4 begun)."""
    rd3_dir, new_root = Path(rd3_dir), Path(new_root)
    if new_root.exists():
        raise Resume4Error(f"{new_root} exists (never overwritten)")
    (new_root / "base").mkdir(parents=True)
    (new_root / "derived").mkdir()
    base_hashes: Dict[str, str] = {}
    for n in (*march.DATA_FILES, march.MANIFEST):
        src, dst = rd3_dir / "archive" / n, new_root / "base" / n
        shutil.copyfile(src, dst)
        base_hashes[n] = rs.sha256_file(dst)
        if base_hashes[n] != rs.sha256_file(src):
            raise Resume4Error(f"the base copy of {n} differs from rd3's file")
    if march.verify_manifest(new_root / "base"):
        raise Resume4Error("the base copy's manifest does not verify")
    a, _meta = s4.Archive4.read_dir(new_root / "base", floor_min=floor_min)
    ov_path = new_root / "derived" / "open_overlay.jsonl"
    ov_path.write_bytes(overlay["bytes"])
    if hashlib.sha256(ov_path.read_bytes()).hexdigest() != overlay["sha256"]:
        raise Resume4Error("the stored overlay's digest differs")
    (new_root / "derived" / "open_overlay.json").write_text(
        json.dumps({"sha256": overlay["sha256"], "counts": overlay["counts"], "rows": len(overlay["rows"]), "utc": utc, "computed_twice_equal": True,
                    "kind": "the closing v2 overlay of rd3's archive = the overlay at rd4's open (eligibility is unchanged under m8_rd_select_v3)"}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    ev = a.begin_rd4(int(facts["first_rd4_iteration"]), lines_sha256)
    base = {"schema": "m8_rd4_base_v1", "rd3_checkpoint_seq": facts.get("rd3_checkpoint_seq"), "rd3_archive_files_sha256": dict(base_hashes),
            "rd3_close_record_sha256": facts.get("close_record_sha256"), "rd3_manifest": facts.get("manifest"), "rd3_increment": RD3_INCREMENT_NAME,
            "rd3_increment_manifest_sha256": increment_manifest_sha256, "session_event": ev, "overlay_sha256": overlay["sha256"], "inherited": facts.get("inherited"), "utc": utc}
    (new_root / "derived" / "base.json").write_text(json.dumps(base, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    meta = dict(meta_extra, checkpoint_seq=int(facts["rd3_checkpoint_seq"]) + 1, why="open", utc=utc, session="rd4", base=base)
    march.save_checkpoint(new_root / "archive", a, meta)
    pp = rs.prefix_property(rd3_dir / "archive", new_root / "archive")                    # rd4's ledger begins with rd3's exact bytes, from the first checkpoint on
    if not pp["ok"]:
        raise Resume4Error(f"rd4's first checkpoint does not begin with rd3's closing bytes: {pp['problems']}")
    return a


# -- close: the prefix chain -------------------------------------------------------------------------------------------------------------------------


def prefix_chain(rd1_archive: Path, rd2_archive: Path, rd3_archive: Path, rd4_archive: Path) -> Dict[str, Any]:
    """rd2's archive files begin with rd1's bytes, rd3's with rd2's closing bytes and rd4's with rd3's closing bytes (every ledger line, burst index row and word)."""
    a = rs.prefix_property(Path(rd1_archive), Path(rd2_archive))
    b = rs.prefix_property(Path(rd2_archive), Path(rd3_archive))
    c = rs.prefix_property(Path(rd3_archive), Path(rd4_archive))
    return {"rd1_rd2": a, "rd2_rd3": b, "rd3_rd4": c, "ok": bool(a["ok"] and b["ok"] and c["ok"]),
            "problems": [f"rd1->rd2: {p}" for p in a["problems"]] + [f"rd2->rd3: {p}" for p in b["problems"]] + [f"rd3->rd4: {p}" for p in c["problems"]]}
