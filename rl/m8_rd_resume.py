"""M8-rd2 resume: the open protocol R1-R6 of the continuation (proposal section 3.2), zero native ticks, and the close checks.

    R1  rd1 immutability: runs/m8_rd/ holds exactly rd1's files, each byte-identical to its D: increment (size, mtime, sha256)
    R2  the rd1 archive reads (manifest verified), checkpoint 7 / previous 6, the manifest equals rd1's close record
    R3  the pins equal the archive's (executable, runtime files, frozen configuration, flags, contract digests, tick-0 record)
    R4  rd1's own audit (rl/m8_rd_archive.audit, unchanged): the ledger rebuilds every cell byte for byte under v1
    R5  the v2 overlay of the rd1 cells, computed twice (incremental and first-principles) and equal, with its digest and the
        figures the proposal reports (2,454 of 6,960 eligible cells excluded; every launch-capable, step-contact and grounded
        cell still eligible)
    R6  materialise runs/m8_rd_rd2/: rd1's five data files copied byte for byte (hashes equal), the overlay, the `session` event
        and the first v2 checkpoint, with a base record that names rd1's manifest, close record and D: increment

Nothing here writes under runs/m8_rd/ (a static test guards that). rd1's tree is only read.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402

RESUME_CONTRACT = "m8_rd_resume_v1"
RD1_ARCHIVE_ID = "m8_rd_a1"
RD1_INCREMENT_NAME = "2026-10-02_incr_m8_rd1"
RD1_INCREMENT_MANIFEST_SHA256 = "e81226d7f36a28a09966b577bfd95cbee093fbdf91f2714b9d28d3a7046103f4"
RD1_FACTS = {"files": 166, "bytes": 62_448_635, "cells": 8264, "bursts": 2175, "events": 4350, "checkpoint_seq": 7,
             "previous_checkpoint_seq": 6, "exploration_ticks": 2_435_663, "dispatch_iterations": (0, 2174), "first_rd2_iteration": 2175}

# the figures the proposal's section 2.4(d) reports for the rd2 open (Part B condition 5: any difference stops the run)
EXPECTED_OPEN = {"cells": 8264, "eligible_v1": 6960, "descent_among_v1_eligible": 1905, "bound_among_v1_eligible": 1309, "union": 2454,
                 "eligible_v2": 4506, "descent_by_region": {"below": 1307, "beside": 424, "onlow": 129, "onhigh": 45},
                 "bound_by_class": {"A2": 0, "A1": 361, "A0": 948}, "bound_below_floor": 1309, "descent_a2a1_on_stage_y_ge_0": 22,
                 "descent_a2_y_ge_0": 8, "descent_launch_capable": 0, "descent_grounded": 0,
                 "still_eligible": {"launch_capable": 14, "step_contact": 32, "grounded": 201},
                 "a2a1_on_stage_y_ge_0_v1_eligible": 403, "launch_capable_cells": 14}


class ResumeError(RuntimeError):
    """The open protocol failed (the session is refused, nothing runs)."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -- R1: rd1 immutability ---------------------------------------------------------------------------------------------------------


def rd1_immutability(rd1_root: Path, increment_dir: Path, *, check_backup_bytes: bool = True) -> Dict[str, Any]:
    """The rd1 tree equals its D: increment's manifest exactly (same paths, sizes, mtimes, sha256), the increment's verification record
    says PASS, and (optionally) the backup's own bytes hash to the same values. Reads only."""
    import runs_backup as rb

    rd1_root, increment_dir = Path(rd1_root), Path(increment_dir)
    problems: List[str] = []
    rec_path = increment_dir / rb.RECORD
    rec = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.is_file() else {}
    if rec.get("result") != "PASS":
        problems.append(f"the increment's verification record is {rec.get('result')!r}")
    if not (increment_dir / rb.MANIFEST).is_file():
        problems.append("the increment has no manifest")
        return {"ok": False, "problems": problems}
    msha = sha256_file(increment_dir / rb.MANIFEST)
    if rec.get("manifest_sha256") != msha:
        problems.append("the manifest on disk differs from the verified one")
    manifest = rb.read_manifest(increment_dir)
    files, _skipped, errors = rb.walk(rd1_root)
    problems += [f"unreadable: {e}" for e in errors[:5]]
    missing = sorted(set(manifest) - set(files))
    extra = sorted(set(files) - set(manifest))
    problems += [f"in the increment, not in rd1's tree: {r}" for r in missing[:5]]
    problems += [f"in rd1's tree, not in the increment: {r}" for r in extra[:5]]
    changed = sorted(r for r in set(manifest) & set(files) if (manifest[r][1], manifest[r][2]) != files[r])
    problems += [f"size or mtime differs: {r}" for r in changed[:5]]
    bad: List[str] = []
    for rel in sorted(set(manifest) & set(files)):
        if rb.sha256_of(rb.native(rd1_root, rel)) != manifest[rel][0]:
            bad.append(rel)
        elif check_backup_bytes and rb.sha256_of(rb.native(increment_dir / "runs", rel)) != manifest[rel][0]:
            bad.append(f"{rel} (backup copy)")
    problems += [f"sha256 differs: {r}" for r in bad[:5]]
    return {"ok": not problems, "problems": problems, "files": len(files), "manifest_files": len(manifest), "manifest_sha256": msha,
            "bytes": sum(s for s, _m in files.values()), "increment_record": {k: rec.get(k) for k in ("result", "files", "bytes", "verified_utc")}}


# -- R2 / R4: the rd1 archive ------------------------------------------------------------------------------------------------------


def rd1_archive_facts(rd1_root: Path, expect: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Read and audit rd1's archive with rd1's own code: manifest, checkpoints, close record, counts, and the ledger audit. `expect` =
    the registered facts (RD1_FACTS; parameter for the tests on synthetic trees only)."""
    E = dict(RD1_FACTS if expect is None else expect)
    rd1_root = Path(rd1_root)
    problems: List[str] = []
    best, meta, report = march.load_latest_verified(rd1_root / "archive")
    seqs = {r["dir"]: r.get("checkpoint_seq") for r in report if r["state"] == "verified"}
    if best is None or meta is None:
        return {"ok": False, "problems": ["no verified checkpoint"], "checkpoints": report}
    if int(meta["checkpoint_seq"]) != E["checkpoint_seq"] or seqs.get("archive.prev") != E["previous_checkpoint_seq"]:
        problems.append(f"checkpoints {seqs}, expected {E['checkpoint_seq']} / {E['previous_checkpoint_seq']}")
    arch, meta = march.Archive.read_files(rd1_root / "archive")
    counts = (len(arch.cells), len(arch.bursts), len(arch.events))
    if counts != (E["cells"], E["bursts"], E["events"]):
        problems.append(f"counts {counts}")
    close_p = rd1_root / "sessions" / "rd1" / "close.json"
    close = json.loads(close_p.read_text(encoding="utf-8")) if close_p.is_file() else {}
    manifest = {n: march.sha256_file(rd1_root / "archive" / n) for n in march.DATA_FILES}
    if (close.get("archive") or {}).get("manifest") != manifest:
        problems.append("the archive's files differ from rd1's close record")
    if (close.get("archive") or {}).get("checkpoint_seq") != E["checkpoint_seq"]:
        problems.append("the close record's checkpoint sequence differs")
    if meta.get("archive_id") != RD1_ARCHIVE_ID or meta.get("schema") != march.ARCHIVE_SCHEMA or meta.get("select_contract") != march.SELECT_CONTRACT:
        problems.append("archive id, schema or select contract differs")
    its = sorted(e["it"] for e in arch.events if e["ev"] == "dispatch")
    if its != list(range(E["dispatch_iterations"][0], E["dispatch_iterations"][1] + 1)):
        problems.append(f"the dispatch iterations are not the contiguous {E['dispatch_iterations'][0]}..{E['dispatch_iterations'][1]}")
    if any(e["ev"] == "fail" for e in arch.events):
        problems.append("the ledger holds fail events")
    aud = march.audit(arch)
    if not aud["ok"]:
        problems += [f"audit: {p}" for p in aud["problems"][:5]]
    return {"ok": not problems, "problems": problems, "checkpoints": seqs, "counts": {"cells": counts[0], "bursts": counts[1], "events": counts[2]},
            "manifest": manifest, "close_record_sha256": sha256_file(close_p) if close_p.is_file() else None, "audit": aud,
            "select_digest": meta.get("select_digest"), "pin_tick0": meta.get("pin_tick0"), "pins": meta.get("pins"),
            "dispatch_iterations": [its[0], its[-1]] if its else None, "ticks": meta.get("ticks"),
            "rd1_checkpoint_seq": int(meta["checkpoint_seq"]), "first_rd2_iteration": (its[-1] + 1) if its else 0}


# -- R3: pins ------------------------------------------------------------------------------------------------------------------------


def pin_problems(meta_pins: Mapping[str, Any], now: Mapping[str, Any], frozen_dir: Path, frozen_expected: Mapping[str, str]) -> List[str]:
    """Differences between the archive's pins and the current identity. `now` = {executable_sha256, runtime_files, contracts, flags}.
    The executable alone differing is reported separately by the caller (decision 11: re-verification, not exploration)."""
    problems: List[str] = []
    for k in ("executable_sha256", "runtime_files", "contracts", "flags"):
        if json.dumps(meta_pins.get(k), sort_keys=True) != json.dumps(now.get(k), sort_keys=True):
            problems.append(f"pin {k} differs")
    if dict(meta_pins.get("frozen_sha256") or {}) != dict(frozen_expected):
        problems.append("the pinned frozen-configuration hashes differ from the expected ones")
    for n, h in dict(frozen_expected).items():
        p = Path(frozen_dir) / n
        if not p.is_file() or sha256_file(p) != h:
            problems.append(f"frozen file {n} differs from its pin")
    return problems


# -- R5: the overlay ----------------------------------------------------------------------------------------------------------------


def build_overlay(rd1_archive_dir: Path, floor_min: Optional[float] = None) -> Dict[str, Any]:
    """The v2 flags of every rd1 cell, computed twice (the incremental structures of one load and the first-principles recomputation of
    another) and required equal; with the bytes, their sha256 and the proposal's figures."""
    a, _meta = s2.Archive2.read_dir(rd1_archive_dir, floor_min=floor_min)
    rows_a = s2.overlay_rows(a)
    b, _m = s2.Archive2.read_dir(rd1_archive_dir, floor_min=floor_min)
    desc, bound = b.reference_flags()
    rows_b = s2.overlay_rows(b, desc, bound)
    ba, bb = s2.overlay_bytes(rows_a), s2.overlay_bytes(rows_b)
    counts = s2.overlay_counts(a, rows_a)
    problems = [] if ba == bb else ["the overlay computed twice differs"]
    return {"ok": not problems, "problems": problems, "rows": rows_a, "bytes": ba, "sha256": hashlib.sha256(ba).hexdigest(),
            "counts": counts, "archive": a}


def expected_open_problems(counts: Mapping[str, Any]) -> List[str]:
    out = []
    for k, want in EXPECTED_OPEN.items():
        if json.dumps(counts.get(k), sort_keys=True) != json.dumps(want, sort_keys=True):
            out.append(f"{k}: {counts.get(k)} (the proposal reports {want})")
    return out


# -- R6: materialise ------------------------------------------------------------------------------------------------------------------


def materialise(rd1_root: Path, rd2_root: Path, *, facts: Mapping[str, Any], overlay: Mapping[str, Any], lines_sha256: str,
                meta_extra: Mapping[str, Any], increment_manifest_sha256: str, utc: str,
                floor_min: Optional[float] = None) -> s2.Archive2:
    """Create rd2's tree: base/ (rd1's data files, byte for byte), derived/ (the open overlay and its digest) and the first v2 checkpoint
    in archive/ (rd1's cells and ledger plus the `session` event). Returns the v2 archive (mode 2)."""
    rd1_root, rd2_root = Path(rd1_root), Path(rd2_root)
    if rd2_root.exists():
        raise ResumeError(f"{rd2_root} exists (never overwritten)")
    (rd2_root / "base").mkdir(parents=True)
    (rd2_root / "derived").mkdir()
    base_hashes: Dict[str, str] = {}
    for n in (*march.DATA_FILES, march.MANIFEST):
        src, dst = rd1_root / "archive" / n, rd2_root / "base" / n
        shutil.copyfile(src, dst)
        base_hashes[n] = sha256_file(dst)
        if base_hashes[n] != sha256_file(src):
            raise ResumeError(f"the base copy of {n} differs from rd1's file")
    if march.verify_manifest(rd2_root / "base"):
        raise ResumeError("the base copy's manifest does not verify")
    a, _meta = s2.Archive2.read_dir(rd2_root / "base", floor_min=floor_min)
    ov_path = rd2_root / "derived" / "open_overlay.jsonl"
    ov_path.write_bytes(overlay["bytes"])
    if hashlib.sha256(ov_path.read_bytes()).hexdigest() != overlay["sha256"]:
        raise ResumeError("the stored overlay's digest differs")
    (rd2_root / "derived" / "open_overlay.json").write_text(
        json.dumps({"sha256": overlay["sha256"], "counts": overlay["counts"], "rows": len(overlay["rows"]), "utc": utc,
                    "computed_twice_equal": True}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    ev = a.begin_v2(int(facts["first_rd2_iteration"]), lines_sha256)
    base = {"schema": "m8_rd2_base_v1", "rd1_root": str(rd1_root), "rd1_checkpoint_seq": facts.get("rd1_checkpoint_seq"),
            "rd1_archive_files_sha256": {n: h for n, h in base_hashes.items()}, "rd1_close_record_sha256": facts.get("close_record_sha256"),
            "rd1_manifest": facts.get("manifest"), "rd1_increment": RD1_INCREMENT_NAME,
            "rd1_increment_manifest_sha256": increment_manifest_sha256, "session_event": ev, "overlay_sha256": overlay["sha256"], "utc": utc}
    (rd2_root / "derived" / "base.json").write_text(json.dumps(base, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    meta = dict(meta_extra, checkpoint_seq=int(facts["rd1_checkpoint_seq"]) + 1, why="open", utc=utc, session="rd2", base=base)
    march.save_checkpoint(rd2_root / "archive", a, meta)
    return a


# -- close: the prefix property ----------------------------------------------------------------------------------------------------------


def prefix_property(rd1_archive_dir: Path, rd2_archive_dir: Path) -> Dict[str, Any]:
    """rd2's files begin with rd1's exact bytes where rd1 wrote them: every ledger line, every burst index row and every word of rd1's
    archive (for the real tree: the first 4,350 events, the first 2,175 index rows and the first 237,209 bytes of the word file)."""
    out: Dict[str, Any] = {"problems": []}
    for name in ("events.jsonl", "bursts.idx.jsonl", "bursts.bin"):
        a = (Path(rd1_archive_dir) / name).read_bytes()
        b = (Path(rd2_archive_dir) / name).read_bytes()
        ok = b[:len(a)] == a
        out[name] = {"bytes": len(a), "lines": a.count(b"\n") if name != "bursts.bin" else None, "identical": bool(ok)}
        if not ok:
            out["problems"].append(f"{name}: rd2's file does not begin with rd1's bytes")
    out["ok"] = not out["problems"]
    return out
