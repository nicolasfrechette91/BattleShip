"""M8-rd3: the archive that continues rd2's closing archive (rd1 + rd2) under the UNCHANGED selection `m8_rd_select_v2` (pure, stdlib only).

Design: docs/rl_m8_rd3_decisions_2026-10-02.md (the user's decisions for rd3 and the mechanical readings I1-I14).

`Archive3` extends rd2's `Archive2` (`rl/m8_rd_select2.py`, untouched) with exactly one thing: the keyed-draw identity of a session. The selection rules,
eligibility E1-E6, X1, the burst tree, the recovery bound, replacement, ingestion, persistence and the open overlay are rd2's code, called as they are. What is new:

    * a second `session` event (name `rd3`) whose digest is RECOMPUTED from the current selection contract and must equal the digest of rd2's
      `session` event: the equality is the proof that the selection, the bound and the status table are unchanged;
    * the draw id by iteration: iterations before rd3's first use rd2's draw id (`m8_rd_a1_v2`, and rd1's own key in rd1's part of the ledger), iterations from
      rd3's first use `m8_rd_a1_rd3` (`m8_rd|m8_rd_a1_rd3|select|<iteration>`, explorer `m8_rd|m8_rd_a1_rd3|explore|<iteration>|<decision index>`);
    * `rebuild3` / `audit3`: the ledger rebuild of all three parts (rd1 under v1, rd2 under v2, rd3 under v2 with the rd3 draws), every selection re-derived and every
      insert / replace / keep decision re-checked. rd2's `rebuild2` cannot cross a second `session` event, so this is its three-part twin.

Nothing here reads a position, a surface, a target location or a direction in a PREFERENCE (that is rd2's property, kept).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import m8_rd_archive as march
import m8_rd_cells as mcell
import m8_rd_select2 as s2

ARCHIVE3_CONTRACT = "m8_rd3_archive_v1"
SESSION_NAME_RD2 = s2.SESSION_NAME                 # "rd2"
SESSION_NAME = "rd3"
DRAW_SUFFIX_RD2 = s2.DRAW_SUFFIX                   # "_v2"
DRAW_SUFFIX = "_rd3"


class Select3Error(RuntimeError):
    """A violated rd3 archive invariant (never silently tolerated)."""


def draws_description() -> Dict[str, Any]:
    return {"select": f"m8_rd|<archive id>{DRAW_SUFFIX}|select|<iteration>", "explore": f"m8_rd|<archive id>{DRAW_SUFFIX}|explore|<iteration>|<decision index>",
            "identity_open": "m8_rd|<archive id>|identity_open|rd3|<cell id>", "identity_close": "m8_rd|<archive id>|identity_close|rd3|<cell id>",
            "rd2_select": f"m8_rd|<archive id>{DRAW_SUFFIX_RD2}|select|<iteration>", "rd1_select": "m8_rd|<archive id>|select|<iteration>"}


def draws_digest() -> str:
    return hashlib.sha256(json.dumps(draws_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class Archive3(s2.Archive2):
    """rd2's archive plus the session-dependent draw id. Modes: 1 (rd1's part of the ledger, v1 rules), 2 (v2 rules). The draw id depends on the iteration."""

    def __init__(self, archive_id: str, *, clf: Optional[mcell.Classifier] = None, floor_min: Optional[float] = None):
        super().__init__(archive_id, clf=clf, floor_min=floor_min)
        self.draw_id_rd2 = str(archive_id) + DRAW_SUFFIX_RD2
        self.draw_id_rd3 = str(archive_id) + DRAW_SUFFIX
        self.rd2_first_iteration: Optional[int] = None
        self.rd3_first_iteration: Optional[int] = None

    # -- the draw id ---------------------------------------------------------------------------------------------------------

    def draw_for(self, iteration: int) -> str:
        """The draw id of an iteration: rd3's from rd3's first iteration on, rd2's before (the id the explorer and the selection key use)."""
        if self.rd3_first_iteration is not None and int(iteration) >= self.rd3_first_iteration:
            return self.draw_id_rd3
        return self.draw_id_rd2

    def select(self, iteration: int) -> march.Cell:
        keep = self.draw_id
        self.draw_id = self.draw_for(iteration)
        try:
            return super().select(iteration)             # rd2's selection, byte for byte, with this iteration's draw id (mode 1 ignores it)
        finally:
            self.draw_id = keep

    # -- the session switches ----------------------------------------------------------------------------------------------------

    def begin_v2(self, first_iteration: int, lines_sha256: str) -> Dict[str, Any]:
        ev = super().begin_v2(first_iteration, lines_sha256)
        self.rd2_first_iteration = int(first_iteration)
        return ev

    def begin_rd3(self, first_iteration: int, lines_sha256: str) -> Dict[str, Any]:
        """Add rd3's `session` event. The digest is recomputed from the current contract and must equal rd2's session digest (selection unchanged)."""
        if self.mode != 2 or self.rd2_first_iteration is None:
            raise Select3Error("rd3 begins only after rd2's session event")
        if self.rd3_first_iteration is not None:
            raise Select3Error("rd3 has already begun")
        if self._pending:
            raise Select3Error(f"{len(self._pending)} dispatched iterations are still pending")
        sess = [e for e in self.events if e["ev"] == "session"]
        if [e.get("name") for e in sess] != [SESSION_NAME_RD2]:
            raise Select3Error(f"session events before rd3: {[e.get('name') for e in sess]}")
        prior = [e["it"] for e in self.events if e["ev"] == "dispatch"]
        if prior and int(first_iteration) <= max(prior):
            raise Select3Error(f"first iteration {first_iteration} would reuse iteration {max(prior)}")
        digest = s2.select2_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min)
        if digest != sess[0]["digest"]:
            raise Select3Error("the selection contract digest differs from rd2's session event: this is not a continuation under m8_rd_select_v2 unchanged")
        ev = {"ev": "session", "name": SESSION_NAME, "select": s2.SELECT2_CONTRACT, "digest": digest, "first_iteration": int(first_iteration),
              "draw_suffix": DRAW_SUFFIX}
        self.events.append(ev)
        self.rd3_first_iteration = int(first_iteration)
        self.first_iteration = int(first_iteration)
        self.draw_id = self.draw_id_rd3
        self._version += 1
        return ev

    # -- ranges of the three parts -----------------------------------------------------------------------------------------------

    def iteration_ranges(self) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        """(first, last) dispatch iteration of rd1, rd2 and rd3 (None where a part has none)."""
        its = sorted(e["it"] for e in self.events if e["ev"] == "dispatch")
        r2 = self.rd2_first_iteration
        r3 = self.rd3_first_iteration
        p1 = [i for i in its if r2 is None or i < r2]
        p2 = [i for i in its if r2 is not None and i >= r2 and (r3 is None or i < r3)]
        p3 = [i for i in its if r3 is not None and i >= r3]
        rng = lambda xs: (xs[0], xs[-1]) if xs else (None, None)      # noqa: E731
        return {"rd1": rng(p1), "rd2": rng(p2), "rd3": rng(p3)}

    # -- construction from an rd2-readable archive -------------------------------------------------------------------------------

    @classmethod
    def adopt(cls, a: s2.Archive2) -> "Archive3":
        """The same archive state as `a` (rd2's loader did the work), as an Archive3. Requires rd2's session event, and rd3's if present."""
        out = cls.__new__(cls)
        out.__dict__.update(a.__dict__)
        out.draw_id_rd2 = str(out.archive_id) + DRAW_SUFFIX_RD2
        out.draw_id_rd3 = str(out.archive_id) + DRAW_SUFFIX
        out.rd2_first_iteration = None
        out.rd3_first_iteration = None
        sess = [e for e in out.events if e["ev"] == "session"]
        names = [e.get("name") for e in sess]
        if names not in ([SESSION_NAME_RD2], [SESSION_NAME_RD2, SESSION_NAME]):
            raise Select3Error(f"session events {names}: an rd3 archive carries rd2's and at most rd3's")
        out.rd2_first_iteration = int(sess[0]["first_iteration"])
        if len(sess) == 2:
            out.rd3_first_iteration = int(sess[1]["first_iteration"])
            out.draw_id = out.draw_id_rd3
        else:
            out.draw_id = out.draw_id_rd2
        return out

    @staticmethod
    def read_dir(directory: Path, *, clf: Optional[mcell.Classifier] = None, floor_min: Optional[float] = None) -> Tuple["Archive3", Dict[str, Any]]:
        """Load an archive directory (rd2's closing archive or an rd3 checkpoint) after verifying its manifest; the derived state is rebuilt."""
        a, meta = s2.Archive2.read_dir(directory, clf=clf, floor_min=floor_min)
        return Archive3.adopt(a), meta

    # -- persistence -------------------------------------------------------------------------------------------------------------

    def write_files(self, directory: Path, meta: Mapping[str, Any]) -> Dict[str, str]:
        extra = dict(meta, archive3_contract=ARCHIVE3_CONTRACT, rd2_first_iteration=self.rd2_first_iteration, rd3_first_iteration=self.rd3_first_iteration,
                     draw_ids={"rd1": self.archive_id, "rd2": self.draw_id_rd2, "rd3": self.draw_id_rd3 if self.rd3_first_iteration is not None else None})
        return super().write_files(directory, extra)


# -- the ledger rebuild and audit (three parts) ----------------------------------------------------------------------------------------


def rebuild3(saved: s2.Archive2, lines_sha256: str) -> Archive3:
    """Replay the ordered ledger over the stored bursts: rd1's part under v1, rd2's `session` event and part under v2 (draw id `_v2`), rd3's `session` event and part under v2
    (draw id `_rd3`). Every selection is re-derived and every insert / replace / keep decision is re-checked. Zero native ticks."""
    if not saved.cells:
        raise march.ArchiveError("nothing to rebuild")
    out = Archive3(saved.archive_id, clf=saved.clf, floor_min=saved.floor_min)
    c0 = saved.cells[0]
    out.init_cell0(c0.key, c0.end, c0.end_digest, c0.chain)
    out.cells[0].first_cum = c0.first_cum
    bursts = {b.id: b for b in saved.bursts}
    for ev in saved.events:
        kind = ev["ev"]
        if kind == "dispatch":
            chosen = out.select(ev["it"])
            if chosen.id != ev["cell"]:
                raise march.ArchiveError(f"iteration {ev['it']}: the rebuilt selection is cell {chosen.id}, the ledger says {ev['cell']}")
            out.apply_dispatch(ev["it"], ev["cell"], ev["worker"])
        elif kind == "fail":
            out.note_failure(ev["it"], ev["why"])
        elif kind == "session":
            if ev.get("name") == SESSION_NAME_RD2:
                made = out.begin_v2(int(ev["first_iteration"]), lines_sha256)
            elif ev.get("name") == SESSION_NAME:
                made = out.begin_rd3(int(ev["first_iteration"]), lines_sha256)
            else:
                raise march.ArchiveError(f"unknown session event {ev}")
            if made != ev:
                raise march.ArchiveError(f"the rebuilt session event {made} differs from the ledger's {ev}")
        elif kind == "ingest":
            if ev["burst"] == -1:
                out._pending.pop(ev["it"], None)
                out.events.append(dict(ev))
                continue
            s2._apply_stored_burst2(out, bursts[ev["burst"]])
        else:
            raise march.ArchiveError(f"unknown ledger event {ev}")
    return out


def audit3(saved: s2.Archive2, lines_sha256: str) -> Dict[str, Any]:
    """The close audit of the three-part archive: the ledger rebuilds it exactly; every prefix reconstructs; the incremental derived state equals the first-principles
    recomputation; the dispatch iterations are strictly increasing and never reused; every session event precedes the dispatches of its part."""
    problems: List[str] = []
    try:
        rebuilt = rebuild3(saved, lines_sha256)
        a = [json.dumps(c.to_json(), sort_keys=True) for c in saved.cells]
        b = [json.dumps(c.to_json(), sort_keys=True) for c in rebuilt.cells]
        if len(a) != len(b):
            problems.append(f"the rebuilt archive has {len(b)} cells, the saved one {len(a)}")
        else:
            diff = [i for i in range(len(a)) if a[i] != b[i]]
            if diff:
                problems.append(f"{len(diff)} cells differ after the rebuild (first: {diff[:5]})")
        if len(saved.bursts) != len(rebuilt.bursts):
            problems.append("burst counts differ after the rebuild")
        else:
            bj = [json.dumps(x.to_json(0), sort_keys=True) for x in saved.bursts]
            bk = [json.dumps(x.to_json(0), sort_keys=True) for x in rebuilt.bursts]
            if bj != bk:
                problems.append("the rebuilt burst records differ from the saved ones")
        if saved.events != rebuilt.events:
            problems.append("the rebuilt ledger differs from the saved one")
        if saved.diag != rebuilt.diag:
            problems.append("the rebuilt velocity-reversal reading differs from the saved one")
        if saved.diag2 != rebuilt.diag2:
            problems.append("the rebuilt v2 counters differ from the saved ones")
        if saved.desc != rebuilt.desc or saved.bound != rebuilt.bound:
            problems.append("the rebuilt derived flags differ from the saved archive's")
    except (march.ArchiveError, Select3Error, s2.Select2Error, KeyError, IndexError, ValueError, TypeError) as exc:
        problems.append(f"rebuild failed: {type(exc).__name__}: {exc}")
    try:
        ref_desc, ref_bound = saved.reference_flags()
        if ref_desc != saved.desc:
            problems.append(f"{sum(x != y for x, y in zip(ref_desc, saved.desc))} descent flags differ from the first-principles recomputation")
        if ref_bound != saved.bound:
            problems.append("the bound flags differ from the first-principles recomputation")
    except (IndexError, KeyError, ValueError) as exc:
        problems.append(f"the first-principles recomputation failed: {type(exc).__name__}: {exc}")
    its = [e["it"] for e in saved.events if e["ev"] == "dispatch"]
    if its != sorted(set(its)):
        problems.append("the dispatch iterations are not strictly increasing (an iteration was reused)")
    last_seen_it = -1
    floor_it: Optional[int] = None                       # the first iteration of the part the ledger is in (None before rd2's session event)
    for e in saved.events:
        if e["ev"] == "dispatch":
            last_seen_it = int(e["it"])
            if floor_it is not None and last_seen_it < floor_it:
                problems.append(f"dispatch {last_seen_it} lies before the first iteration {floor_it} of the session it follows")
        elif e["ev"] == "session":
            if int(e["first_iteration"]) <= last_seen_it:
                problems.append(f"session event {e.get('name')}: first iteration {e['first_iteration']} is not after the dispatches before it (last {last_seen_it})")
            floor_it = int(e["first_iteration"])
    lengths_ok = 0
    for c in saved.cells:
        try:
            saved.cell_words(c)
            lengths_ok += 1
        except march.ArchiveError as exc:
            problems.append(f"cell {c.id}: {exc}")
            if len(problems) > 20:
                break
    return {"ok": not problems, "problems": problems[:20], "cells": len(saved.cells), "bursts": len(saved.bursts), "events": len(saved.events),
            "prefixes_reconstructed": lengths_ok}
