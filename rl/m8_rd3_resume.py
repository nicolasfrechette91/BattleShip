"""M8-rd3 resume: the open protocol of the second continuation, two levels deep (zero native ticks), and the close checks.

rd2's protocol (rl/m8_rd_resume.py, unchanged and reused wherever it is generic) resumed rd1's closed tree. rd3 resumes rd2's closed tree, which itself continues rd1's:

    R1  immutability of BOTH earlier trees: runs/m8_rd/ and runs/m8_rd_rd2/ each hold exactly the files of their D: increment (paths, sizes, mtimes, sha256, and the
        backup's own bytes), each increment's record says PASS
    R2  rd1's archive facts (rd1's own audit) and rd2's closing archive facts: manifest verified, checkpoint 20 / previous 19, the five files equal rd2's close record,
        the counts (19,062 cells, 6,212 bursts, 12,425 events), the dispatch iterations 0..6,211 contiguous, no `fail` event, exactly one `session` event (rd2) whose digest equals the
        digest RECOMPUTED from the current selection contract (selection unchanged), the diag2 counters equal rd2's close record
    R3  the pins equal the archive's (executable, runtime files, frozen configuration, flags, contract digests including m8_rd_select_v2)
    R4  the ledger rebuild of rd2's closing archive (rd2's own `audit2`: rd1 part under v1, rd2 part under v2, zero ticks) and the prefix property rd1 -> rd2
    R5  the closing v2 overlay of rd2's archive, computed twice (incremental and first-principles) and equal, with its digest, equal to the overlay counts rd2's close record
        stores (19,062 cells, 16,221 v1-eligible, 2,992 descent, 2,087 bound, 4,427 union, 11,794 eligible)
    R6  materialise runs/m8_rd_rd3/: rd2's five closing data files and manifest copied byte for byte into base/ (hashes equal), the overlay, a base record, rd3's `session` event
        and the first rd3 checkpoint (sequence 21)

Nothing here writes under runs/m8_rd/ or runs/m8_rd_rd2/ (a static test guards that). Both trees are only read.
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
import m8_rd_resume as rs  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd3_select as s3  # noqa: E402

RESUME3_CONTRACT = "m8_rd3_resume_v1"
RD2_INCREMENT_NAME = "2026-10-02_incr_m8_rd2"
RD2_INCREMENT_MANIFEST_SHA256 = "6775281e6f1618c5e2304980ca83c78ca049813a53605df791404ec32fd3e9f1"
RD2_FACTS = {"files": 62, "bytes": 66_759_098, "increment_manifest_sha256": RD2_INCREMENT_MANIFEST_SHA256, "cells": 19062, "bursts": 6212, "events": 12425, "checkpoint_seq": 20, "previous_checkpoint_seq": 19,
             "exploration_ticks": 4_992_640, "dispatch_iterations": (0, 6211), "first_rd2_iteration": 2175, "first_rd3_iteration": 6212, "returns": 4037,
             "rd2_cells_created": 10798, "outcome": "PROGRESS_WALL_TOP", "m": 1}
# the closing overlay of rd2's archive (its close record, `archive.overlay_close`): the headline figures the open must reproduce exactly
EXPECTED_CLOSE_OVERLAY = {"cells": 19062, "eligible_v1": 16221, "descent_among_v1_eligible": 2992, "bound_among_v1_eligible": 2087, "union": 4427, "eligible_v2": 11794,
                          "launch_capable_cells": 509, "grounded_cells": 409, "step_contact_cells": 56,
                          "still_eligible": {"launch_capable": 487, "step_contact": 56, "grounded": 409}}


class Resume3Error(RuntimeError):
    """The open protocol failed (the session is refused, nothing runs)."""


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# -- prior sessions' recorded milestones (the S2 evaluation reads them, never assumes them) ---------------------------------------------------


def prior_milestones(rd1_dir: Path, rd2_dir: Path) -> Dict[str, Any]:
    """The milestone each earlier session recorded, read from its own files: rd1 (`sessions/rd1/rule.json`: the higher of its two arms) and rd2 (`sessions/rd2/rule.json`)."""
    out: Dict[str, Any] = {}
    p1 = Path(rd1_dir) / "sessions" / "rd1" / "rule.json"
    if p1.is_file():
        r = _read(p1)
        out["rd1"] = {"m": max(int(r["m_T"]), int(r["m_C"])), "outcome": r.get("outcome"), "t_T": r.get("t_T"), "t_C": r.get("t_C"), "source": "sessions/rd1/rule.json"}
    else:
        out["rd1"] = None
    p2 = Path(rd2_dir) / "sessions" / "rd2" / "rule.json"
    if p2.is_file():
        r = _read(p2)
        out["rd2"] = {"m": int(r["m"]), "milestone": r.get("milestone"), "outcome": r.get("outcome"), "source": "sessions/rd2/rule.json"}
    else:
        out["rd2"] = None
    return out


# -- R2 / R4: rd2's closing archive --------------------------------------------------------------------------------------------------------


def rd2_archive_facts(rd1_dir: Path, rd2_dir: Path, lines_sha256: Optional[str] = None, expect: Optional[Mapping[str, Any]] = None, *,
                      with_audit: bool = True, keep_archive: bool = False) -> Dict[str, Any]:
    """Read and audit rd2's closing archive with rd2's own code: manifest, checkpoints, close record, counts, the session event and its digest, the iterations, the ledger audit
    and the prefix property rd1 -> rd2. `expect` = the registered facts (RD2_FACTS; a parameter for the tests on synthetic trees only)."""
    E = dict(RD2_FACTS if expect is None else expect)
    rd1_dir, rd2_dir = Path(rd1_dir), Path(rd2_dir)
    problems: List[str] = []
    best, meta, report = march.load_latest_verified(rd2_dir / "archive")
    seqs = {r["dir"]: r.get("checkpoint_seq") for r in report if r["state"] == "verified"}
    if best is None or meta is None:
        return {"ok": False, "problems": ["no verified checkpoint"], "checkpoints": report}
    if Path(best).name != "archive" or int(meta["checkpoint_seq"]) != E["checkpoint_seq"] or seqs.get("archive.prev") != E["previous_checkpoint_seq"]:
        problems.append(f"checkpoints {seqs} (best {Path(best).name}), expected {E['checkpoint_seq']} / {E['previous_checkpoint_seq']}")
    a, meta = s3.Archive3.read_dir(rd2_dir / "archive")
    lines = str(lines_sha256 if lines_sha256 is not None else (meta.get("pin_tick0") or {}).get("lines"))
    counts = (len(a.cells), len(a.bursts), len(a.events))
    if counts != (E["cells"], E["bursts"], E["events"]):
        problems.append(f"counts {counts}, expected {(E['cells'], E['bursts'], E['events'])}")
    close_p = rd2_dir / "sessions" / "rd2" / "close.json"
    close = _read(close_p) if close_p.is_file() else {}
    manifest = {n: march.sha256_file(rd2_dir / "archive" / n) for n in march.DATA_FILES}
    if (close.get("archive") or {}).get("manifest") != manifest:
        problems.append("the archive's files differ from rd2's close record")
    if (close.get("archive") or {}).get("checkpoint_seq") != E["checkpoint_seq"]:
        problems.append("the close record's checkpoint sequence differs")
    state_p = rd2_dir / "sessions" / "rd2" / "state.json"
    if not state_p.is_file() or _read(state_p).get("phase") != "done":
        problems.append("rd2's session state is not done")
    rule_p = rd2_dir / "sessions" / "rd2" / "rule.json"
    rule_rec = _read(rule_p) if rule_p.is_file() else {}
    if "outcome" in E and (rule_rec.get("outcome") != E["outcome"] or rule_rec.get("m") != E["m"]):
        problems.append(f"rd2's recorded decision {rule_rec.get('outcome')!r} m={rule_rec.get('m')!r} differs from the registered {E['outcome']!r} m={E['m']!r}")
    lt = meta.get("ledger_T") or {}
    if "returns" in E and (lt.get("jobs") != E["returns"] or lt.get("ticks") != E["exploration_ticks"]):
        problems.append(f"rd2's ledger totals {lt} differ from the registered {E['returns']} returns / {E['exploration_ticks']} ticks")
    if meta.get("archive_id") != rs.RD1_ARCHIVE_ID or meta.get("schema") != s2.ARCHIVE_SCHEMA_V2 or meta.get("mode") != 2 or meta.get("select2_contract") != s2.SELECT2_CONTRACT:
        problems.append("archive id, schema, mode or select contract differs")
    sess = [e for e in a.events if e["ev"] == "session"]
    digest_now = s2.select2_contract_digest(a.clf.table_sha256, lines, a.floor_min)
    if len(sess) != 1 or sess[0].get("name") != "rd2" or int(sess[0]["first_iteration"]) != E["first_rd2_iteration"]:
        problems.append(f"session events {[(e.get('name'), e.get('first_iteration')) for e in sess]}, expected rd2's alone at {E['first_rd2_iteration']}")
    elif sess[0]["digest"] != digest_now:
        problems.append("rd2's session digest differs from the digest recomputed from the current selection contract (the selection is not unchanged)")
    its = sorted(e["it"] for e in a.events if e["ev"] == "dispatch")
    if its != list(range(E["dispatch_iterations"][0], E["dispatch_iterations"][1] + 1)):
        problems.append(f"the dispatch iterations are not the contiguous {E['dispatch_iterations'][0]}..{E['dispatch_iterations'][1]}")
    if any(e["ev"] == "fail" for e in a.events):
        problems.append("the ledger holds fail events")
    d2 = close.get("archive", {}).get("diag2") or {}
    cur = {k: (len(v) if isinstance(v, list) else v) for k, v in a.diag2.items()}
    if cur != d2:
        problems.append(f"the diag2 counters {cur} differ from rd2's close record {d2}")
    base_ok = True
    for n in (*march.DATA_FILES, march.MANIFEST):
        pa, pb = rd2_dir / "base" / n, rd1_dir / "archive" / n
        if not (pa.is_file() and pb.is_file() and march.sha256_file(pa) == march.sha256_file(pb)):
            base_ok = False
    if not base_ok:
        problems.append("rd2's base copy differs from rd1's archive files")
    pp = rs.prefix_property(rd1_dir / "archive", rd2_dir / "archive")
    if not pp["ok"]:
        problems += [f"prefix rd1 -> rd2: {p}" for p in pp["problems"]]
    aud: Dict[str, Any] = {"skipped": True}
    if with_audit:
        aud = s2.audit2(a, lines)
        if not aud["ok"]:
            problems += [f"rd2 audit: {p}" for p in aud["problems"][:5]]
    return {"ok": not problems, "problems": problems, "checkpoints": seqs, "counts": {"cells": counts[0], "bursts": counts[1], "events": counts[2]}, "manifest": manifest,
            "close_record_sha256": rs.sha256_file(close_p) if close_p.is_file() else None, "audit": aud, "session_event": sess[0] if sess else None,
            "digest_recomputed": digest_now, "dispatch_iterations": [its[0], its[-1]] if its else None, "diag2": cur, "prefix_rd1_rd2": pp,
            "pin_tick0": meta.get("pin_tick0"), "pins": meta.get("pins"), "ticks": meta.get("ticks"), "ledger_T": meta.get("ledger_T"), "rd2_checkpoint_seq": int(meta["checkpoint_seq"]),
            "first_rd3_iteration": (its[-1] + 1) if its else 0, "lines_sha256": lines, "archive": a if keep_archive else None}


# -- R5: the closing overlay ----------------------------------------------------------------------------------------------------------------


def closing_overlay(rd2_dir: Path, expect: Optional[Mapping[str, Any]] = None, floor_min: Optional[float] = None) -> Dict[str, Any]:
    """The v2 flags of every cell of rd2's closing archive, computed twice (the incremental structures of one load and the first-principles recomputation of another, required
    equal), with the bytes and their sha256, compared with the overlay counts rd2's close record stores and with the registered headline figures (`expect`)."""
    rd2_dir = Path(rd2_dir)
    ov = rs.build_overlay(rd2_dir / "archive", floor_min)
    problems = list(ov["problems"])
    close_p = rd2_dir / "sessions" / "rd2" / "close.json"
    stored = (_read(close_p).get("archive") or {}).get("overlay_close") if close_p.is_file() else None
    if stored is None:
        problems.append("rd2's close record holds no closing overlay")
    elif json.dumps(ov["counts"], sort_keys=True) != json.dumps(stored, sort_keys=True):
        problems.append("the closing overlay counts differ from rd2's close record")
    want = EXPECTED_CLOSE_OVERLAY if expect is None else expect
    for k, v in want.items():
        if json.dumps(ov["counts"].get(k), sort_keys=True) != json.dumps(v, sort_keys=True):
            problems.append(f"overlay {k}: {ov['counts'].get(k)} (registered {v})")
    out = dict(ov, ok=not problems, problems=problems, stored_close_counts=stored)
    out.pop("archive", None)                        # the loaded archive is not kept (memory): the rows, the bytes and the counts are the record
    return out


# -- R6: materialise --------------------------------------------------------------------------------------------------------------------------


def materialise3(rd2_dir: Path, new_root: Path, *, facts: Mapping[str, Any], overlay: Mapping[str, Any], lines_sha256: str, meta_extra: Mapping[str, Any],
                 increment_manifest_sha256: str, utc: str, floor_min: Optional[float] = None) -> s3.Archive3:
    """Create rd3's tree: base/ (rd2's closing data files and manifest, byte for byte), derived/ (the closing overlay of rd2 = the overlay at the open, its digest, the base
    record) and the first rd3 checkpoint in archive/ (rd2's cells and ledger plus rd3's `session` event). Returns the archive (mode 2, rd3 begun)."""
    rd2_dir, new_root = Path(rd2_dir), Path(new_root)
    if new_root.exists():
        raise Resume3Error(f"{new_root} exists (never overwritten)")
    (new_root / "base").mkdir(parents=True)
    (new_root / "derived").mkdir()
    base_hashes: Dict[str, str] = {}
    for n in (*march.DATA_FILES, march.MANIFEST):
        src, dst = rd2_dir / "archive" / n, new_root / "base" / n
        shutil.copyfile(src, dst)
        base_hashes[n] = rs.sha256_file(dst)
        if base_hashes[n] != rs.sha256_file(src):
            raise Resume3Error(f"the base copy of {n} differs from rd2's file")
    if march.verify_manifest(new_root / "base"):
        raise Resume3Error("the base copy's manifest does not verify")
    a, _meta = s3.Archive3.read_dir(new_root / "base", floor_min=floor_min)
    ov_path = new_root / "derived" / "open_overlay.jsonl"
    ov_path.write_bytes(overlay["bytes"])
    if hashlib.sha256(ov_path.read_bytes()).hexdigest() != overlay["sha256"]:
        raise Resume3Error("the stored overlay's digest differs")
    (new_root / "derived" / "open_overlay.json").write_text(
        json.dumps({"sha256": overlay["sha256"], "counts": overlay["counts"], "rows": len(overlay["rows"]), "utc": utc, "computed_twice_equal": True,
                    "kind": "the closing v2 overlay of rd2's archive = the overlay at rd3's open"}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    ev = a.begin_rd3(int(facts["first_rd3_iteration"]), lines_sha256)
    base = {"schema": "m8_rd3_base_v1", "rd2_checkpoint_seq": facts.get("rd2_checkpoint_seq"), "rd2_archive_files_sha256": dict(base_hashes),
            "rd2_close_record_sha256": facts.get("close_record_sha256"), "rd2_manifest": facts.get("manifest"), "rd2_increment": RD2_INCREMENT_NAME,
            "rd2_increment_manifest_sha256": increment_manifest_sha256, "session_event": ev, "overlay_sha256": overlay["sha256"], "utc": utc}
    (new_root / "derived" / "base.json").write_text(json.dumps(base, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    meta = dict(meta_extra, checkpoint_seq=int(facts["rd2_checkpoint_seq"]) + 1, why="open", utc=utc, session="rd3", base=base)
    march.save_checkpoint(new_root / "archive", a, meta)
    pp = rs.prefix_property(rd2_dir / "archive", new_root / "archive")                    # rd3's ledger begins with rd2's exact bytes, from the first checkpoint on
    if not pp["ok"]:
        raise Resume3Error(f"rd3's first checkpoint does not begin with rd2's closing bytes: {pp['problems']}")
    return a


# -- close: the prefix chain ------------------------------------------------------------------------------------------------------------------


def prefix_chain(rd1_archive: Path, rd2_archive: Path, rd3_archive: Path) -> Dict[str, Any]:
    """rd2's archive files begin with rd1's bytes and rd3's begin with rd2's closing bytes (every ledger line, every burst index row and every word)."""
    a = rs.prefix_property(Path(rd1_archive), Path(rd2_archive))
    b = rs.prefix_property(Path(rd2_archive), Path(rd3_archive))
    return {"rd1_rd2": a, "rd2_rd3": b, "ok": bool(a["ok"] and b["ok"]), "problems": [f"rd1->rd2: {p}" for p in a["problems"]] + [f"rd2->rd3: {p}" for p in b["problems"]]}
