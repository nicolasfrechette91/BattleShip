"""M8-sd2: the archive that continues sd1's closing archive (rd1 + rd2 + rd3 + rd4 + sd1) under the selection `m8_rd_select_v4` UNCHANGED, with the record reference moved (pure, stdlib only).

Design: docs/rl_m8_sd2_proposal_2026-10-12.md sections 1 and 5.2, as decided on 2026-10-12 (the same design: S = 120, E7, M = 24, the harmonic level draw, the explorer and the caps all
sd1's; only the reference moves, from rd4's verified clear to sd1's).

v4's contract digest is parametrised by the record reference: sd2's `session` event carries v4's digest at the NEW reference beside sd1's digest at the OLD one (`changed_from`); the
description differs in `record_reference` only (a test asserts it). E7 therefore binds at two bounds in one ledger: sd1's part (its iterations) rebuilds under sd1's bound, sd2's part under
sd2's. `Archive6` extends sd1's `Archive5` (rl/m8_sd1_select.py, untouched) with a sixth session: `bound_for(iteration)` selects the bound by the iteration, `select` applies it, and the
eligible-levels cache is keyed on the active bound as well as on the version and the mode. Iterations of rd1 to sd1 are selected under their own rules, draws and bounds, so the whole
history rebuilds (`rebuild6` / `audit6`, six parts).

Nothing here reads a position, a surface, a target location, a target identity or a direction in a PREFERENCE (v2's property, kept): E7 reads a cell's L and the pinned reference.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import m8_rd_archive as march
import m8_rd_cells as mcell
import m8_rd_select2 as s2
import m8_rd3_select as s3
import m8_rd4_select as s4
import m8_sd1_select as s5

ARCHIVE6_CONTRACT = "m8_sd2_archive_v1"
SELECT4_CONTRACT = s5.SELECT4_CONTRACT             # "m8_rd_select_v4", unchanged
SESSION_NAME_RD2 = s5.SESSION_NAME_RD2
SESSION_NAME_RD3 = s5.SESSION_NAME_RD3
SESSION_NAME_RD4 = s5.SESSION_NAME_RD4
SESSION_NAME_SD1 = s5.SESSION_NAME                 # "sd1"
SESSION_NAME = "sd2"
DRAW_SUFFIX_RD2 = s5.DRAW_SUFFIX_RD2
DRAW_SUFFIX_RD3 = s5.DRAW_SUFFIX_RD3
DRAW_SUFFIX_RD4 = s5.DRAW_SUFFIX_RD4
DRAW_SUFFIX_SD1 = s5.DRAW_SUFFIX                   # "_sd1"
DRAW_SUFFIX = "_sd2"
LENGTH_SCALE_V4 = s5.LENGTH_SCALE_V4               # 120: unchanged
SESSIONS = ("rd1", "rd2", "rd3", "rd4", "sd1", "sd2")
# reused unchanged (the contract, the weights, the overlays)
record_reference_block = s5.record_reference_block
validate_record_reference = s5.validate_record_reference
record_bound_max_L = s5.record_bound_max_L
select4_description = s5.select4_description
select4_contract_digest = s5.select4_contract_digest
restore_v3 = s5.restore_v3
v4_weights = s5.v4_weights
overlay_rows6 = s5.overlay_rows5
overlay_bytes6 = s5.overlay_bytes5
overlay_counts6 = s5.overlay_counts5
dispatch_row = s4.dispatch_row                     # `created_in` reads Archive6.session_of_iteration, so sd2 cells are named


class Select6Error(RuntimeError):
    """A violated sd2 archive invariant (never silently tolerated)."""


# -- the contract -------------------------------------------------------------------------------------------------------------------------------


def reference_change_text(old: Mapping[str, Any], new: Mapping[str, Any]) -> str:
    """The one registered change between sd1's session and sd2's, written from the two reference blocks (never a literal)."""
    return (f"record_reference {int(old['completion_input_tick'])}/{int(old['completion_time_passed'])} ({old['session']} cid {int(old['cid'])}) -> "
            f"{int(new['completion_input_tick'])}/{int(new['completion_time_passed'])} ({new['session']} cid {int(new['cid'])})")


def changed_description_keys(status_table_sha256: str, lines_sha256: str, floor_min: Optional[float], old_reference: Mapping[str, Any], new_reference: Mapping[str, Any], margin: int) -> List[str]:
    """The keys of v4's description that differ between the two references (the proof that only the reference moved)."""
    a = select4_description(status_table_sha256, lines_sha256, floor_min, old_reference, margin)
    b = select4_description(status_table_sha256, lines_sha256, floor_min, new_reference, margin)
    return sorted({k for k in set(a) | set(b) if a.get(k) != b.get(k)})


def draws_description() -> Dict[str, Any]:
    return {"select": f"m8_rd|<archive id>{DRAW_SUFFIX}|select|<iteration>", "explore": f"m8_rd|<archive id>{DRAW_SUFFIX}|explore|<iteration>|<decision index>",
            "identity_open": f"m8_rd|<archive id>|identity_open|{SESSION_NAME}|<cell id>", "identity_close": f"m8_rd|<archive id>|identity_close|{SESSION_NAME}|<cell id>",
            "sd1_select": f"m8_rd|<archive id>{DRAW_SUFFIX_SD1}|select|<iteration>", "rd4_select": f"m8_rd|<archive id>{DRAW_SUFFIX_RD4}|select|<iteration>",
            "rd3_select": f"m8_rd|<archive id>{DRAW_SUFFIX_RD3}|select|<iteration>", "rd2_select": f"m8_rd|<archive id>{DRAW_SUFFIX_RD2}|select|<iteration>",
            "rd1_select": "m8_rd|<archive id>|select|<iteration>"}


def draws_digest() -> str:
    return hashlib.sha256(json.dumps(draws_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- the archive -----------------------------------------------------------------------------------------------------------------------------


class Archive6(s5.Archive5):
    """sd1's archive plus sd2's session: its draw id by iteration, v4's weights unchanged, and the record bound BY ITERATION (sd1's bound for sd1's part, sd2's from sd2's first iteration on)."""

    def __init__(self, archive_id: str, *, clf: Optional[mcell.Classifier] = None, floor_min: Optional[float] = None):
        super().__init__(archive_id, clf=clf, floor_min=floor_min)
        self.draw_id_sd2 = str(archive_id) + DRAW_SUFFIX
        self.sd2_first_iteration: Optional[int] = None
        self.sd1_record_reference: Optional[Dict[str, Any]] = None      # sd1's event's reference (the bound of sd1's part); `record_reference` is the CURRENT one (sd2's once begun)
        self.sd1_margin: Optional[int] = None
        self._elig6: Optional[Tuple[Tuple[int, bool, Optional[int]], Dict[int, List[march.Cell]]]] = None

    # -- the draw id and the bound by iteration -----------------------------------------------------------------------------------------

    def draw_for(self, iteration: int) -> str:
        if self.sd2_first_iteration is not None and int(iteration) >= self.sd2_first_iteration:
            return self.draw_id_sd2
        return super().draw_for(iteration)

    def sd1_bound_max_L(self) -> int:
        if self.sd1_record_reference is None or self.sd1_margin is None:
            raise Select6Error("sd1's record bound is not set (sd1 has not begun)")
        return record_bound_max_L(self.sd1_record_reference["completion_input_tick"], self.sd1_margin)

    def bound_for(self, iteration: int) -> Optional[int]:
        """E7's bound for an iteration: sd2's from sd2's first iteration on, sd1's from sd1's first iteration on, none before (v3 and v2 have no record bound)."""
        it = int(iteration)
        if self.sd2_first_iteration is not None and it >= self.sd2_first_iteration:
            return self.bound_max_L()
        if self.sd1_first_iteration is not None and it >= self.sd1_first_iteration:
            return self.sd1_bound_max_L()
        return None

    def eligible_levels(self) -> Dict[int, List[march.Cell]]:       # type: ignore[override]
        """Keyed on the version, the mode AND the active bound: sd1's and sd2's iterations of one archive have different eligible sets."""
        key = (self._version, bool(self._v4), self._bound_L)
        if self._elig6 is not None and self._elig6[0] == key:
            return self._elig6[1]
        out: Dict[int, List[march.Cell]] = {}
        for lv, cs in self._level_cells.items():
            e = [c for c in cs if self.eligible(c)]
            if e:
                out[lv] = e
        self._elig6 = (key, out)
        return out

    def select(self, iteration: int) -> march.Cell:
        keep = self._bound_L
        b = self.bound_for(iteration)
        if b is not None:
            self._bound_L = b
        try:
            return super().select(iteration)         # sd1's mode switch, rd4's weight switch, rd3's draw-id wrapper, rd2's selection, with this iteration's bound
        finally:
            self._bound_L = keep

    def probabilities_at_bound(self, bound_L: int) -> Dict[int, float]:
        """The analytic v4 selection probability of every eligible cell with E7 at the given bound (a reading: E7's effect at sd1's bound against sd2's on the same archive)."""
        keep = self._bound_L
        self._bound_L = int(bound_L)
        try:
            return self.probabilities("v4")
        finally:
            self._bound_L = keep

    # -- the session switches --------------------------------------------------------------------------------------------------------------

    def begin_sd1(self, first_iteration: int, lines_sha256: str, record_reference: Mapping[str, Any], margin: int) -> Dict[str, Any]:
        ev = super().begin_sd1(first_iteration, lines_sha256, record_reference, margin)
        self.sd1_record_reference = dict(self.record_reference or {})
        self.sd1_margin = self.margin
        return ev

    def begin_sd2(self, first_iteration: int, lines_sha256: str, record_reference: Mapping[str, Any], margin: int) -> Dict[str, Any]:
        """Add sd2's `session` event. v2's digest recomputed from the current contract must equal rd2's and rd3's session digests, v3's must equal rd4's, and v4's AT SD1'S OWN REFERENCE must
        equal sd1's (the earlier sessions ran unchanged; sd1's event is read back for its reference and margin); sd2's own event carries v4's digest at the new reference, with sd1's digest
        and the one registered change (the reference) recorded beside it."""
        if self.mode != 2 or self.rd2_first_iteration is None or self.rd3_first_iteration is None or self.rd4_first_iteration is None or self.sd1_first_iteration is None:
            raise Select6Error("sd2 begins only after rd2's, rd3's, rd4's and sd1's session events")
        if self.sd2_first_iteration is not None:
            raise Select6Error("sd2 has already begun")
        if self._pending:
            raise Select6Error(f"{len(self._pending)} dispatched iterations are still pending")
        sess = [e for e in self.events if e["ev"] == "session"]
        if [e.get("name") for e in sess] != [SESSION_NAME_RD2, SESSION_NAME_RD3, SESSION_NAME_RD4, SESSION_NAME_SD1]:
            raise Select6Error(f"session events before sd2: {[e.get('name') for e in sess]}")
        prior = [e["it"] for e in self.events if e["ev"] == "dispatch"]
        if prior and int(first_iteration) <= max(prior):
            raise Select6Error(f"first iteration {first_iteration} would reuse iteration {max(prior)}")
        validate_record_reference(record_reference)
        if not isinstance(margin, int) or isinstance(margin, bool) or margin < 1:
            raise Select6Error(f"the margin is a positive integer number of ticks, got {margin!r}")
        v2 = s2.select2_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min)
        if sess[0]["digest"] != v2 or sess[1]["digest"] != v2:
            raise Select6Error("the selection contract digest differs from rd2's and rd3's session events (they ran m8_rd_select_v2 unchanged): this is not a continuation of that history")
        v3 = s4.select3_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min)
        if sess[2]["digest"] != v3:
            raise Select6Error("the v3 selection contract digest differs from rd4's session event (rd4 ran m8_rd_select_v3 unchanged): this is not a continuation of that history")
        old = sess[3].get("record_reference")
        validate_record_reference(old)
        old_margin = int(sess[3]["margin"])
        v4_sd1 = select4_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min, old, old_margin)
        if sess[3]["digest"] != v4_sd1:
            raise Select6Error("the v4 selection contract digest at sd1's own reference differs from sd1's session event (sd1 ran m8_rd_select_v4 unchanged): this is not a continuation of that history")
        rr = dict(record_reference)
        v4 = select4_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min, rr, int(margin))
        ev = {"ev": "session", "name": SESSION_NAME, "select": SELECT4_CONTRACT, "digest": v4, "first_iteration": int(first_iteration), "draw_suffix": DRAW_SUFFIX,
              "changed_from": {"select": SELECT4_CONTRACT, "digest": v4_sd1, "changes": [reference_change_text(old, rr)]},
              "record_reference": rr, "margin": int(margin), "length_scale": LENGTH_SCALE_V4}
        self.events.append(ev)
        self.sd1_record_reference = dict(old)
        self.sd1_margin = old_margin
        self.sd2_first_iteration = int(first_iteration)
        self.first_iteration = int(first_iteration)
        self.draw_id = self.draw_id_sd2
        self.record_reference = rr
        self.margin = int(margin)
        self._bound_L = record_bound_max_L(rr["completion_input_tick"], int(margin))
        self._version += 1
        return ev

    # -- ranges of the six parts -----------------------------------------------------------------------------------------------------------

    def iteration_ranges(self) -> Dict[str, Tuple[Optional[int], Optional[int]]]:                  # type: ignore[override]
        its = sorted(e["it"] for e in self.events if e["ev"] == "dispatch")
        firsts = [self.rd2_first_iteration, self.rd3_first_iteration, self.rd4_first_iteration, self.sd1_first_iteration, self.sd2_first_iteration]
        bounds: List[Tuple[Optional[int], Optional[int]]] = []
        lo: Optional[int] = None
        for f in firsts + [None]:
            bounds.append((lo, f))
            lo = f
        out: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
        for name, (lo_, hi_) in zip(SESSIONS, bounds):
            if name != "rd1" and lo_ is None:
                out[name] = (None, None)
                continue
            part = [i for i in its if (lo_ is None or i >= lo_) and (hi_ is None or i < hi_)]
            out[name] = (part[0], part[-1]) if part else (None, None)
        return out

    def session_of_iteration(self, iteration: int) -> str:
        out = "rd1"
        for name, first in (("rd2", self.rd2_first_iteration), ("rd3", self.rd3_first_iteration), ("rd4", self.rd4_first_iteration), ("sd1", self.sd1_first_iteration),
                            ("sd2", self.sd2_first_iteration)):
            if first is not None and int(iteration) >= first:
                out = name
        return out

    # -- construction from an rd2-readable archive -----------------------------------------------------------------------------------------

    @classmethod
    def adopt(cls, a: s2.Archive2) -> "Archive6":                    # type: ignore[override]
        """The same archive state as `a` (rd2's loader did the work), as an Archive6. Requires rd2's, rd3's, rd4's and sd1's session events, and sd2's if present (an rd4 archive without sd1's
        event is refused: sd2 continues sd1's closing archive)."""
        out = cls.__new__(cls)
        out.__dict__.update(a.__dict__)
        out.draw_id_rd2 = str(out.archive_id) + DRAW_SUFFIX_RD2
        out.draw_id_rd3 = str(out.archive_id) + DRAW_SUFFIX_RD3
        out.draw_id_rd4 = str(out.archive_id) + DRAW_SUFFIX_RD4
        out.draw_id_sd1 = str(out.archive_id) + DRAW_SUFFIX_SD1
        out.draw_id_sd2 = str(out.archive_id) + DRAW_SUFFIX
        out._v3 = False
        out._v4 = False
        out._elig5 = None
        out._elig6 = None
        sess = [e for e in out.events if e["ev"] == "session"]
        names = [e.get("name") for e in sess]
        four = [SESSION_NAME_RD2, SESSION_NAME_RD3, SESSION_NAME_RD4, SESSION_NAME_SD1]
        if names not in (four, four + [SESSION_NAME]):
            raise Select6Error(f"session events {names}: an sd2 archive carries rd2's, rd3's, rd4's and sd1's and at most sd2's")
        out.rd2_first_iteration = int(sess[0]["first_iteration"])
        out.rd3_first_iteration = int(sess[1]["first_iteration"])
        out.rd4_first_iteration = int(sess[2]["first_iteration"])
        ev1 = sess[3]
        out.sd1_first_iteration = int(ev1["first_iteration"])
        validate_record_reference(ev1["record_reference"])
        out.sd1_record_reference = dict(ev1["record_reference"])
        out.sd1_margin = int(ev1["margin"])
        if len(sess) == 5:
            ev2 = sess[4]
            out.sd2_first_iteration = int(ev2["first_iteration"])
            validate_record_reference(ev2["record_reference"])
            out.record_reference = dict(ev2["record_reference"])
            out.margin = int(ev2["margin"])
            out.draw_id = out.draw_id_sd2
        else:
            out.sd2_first_iteration = None
            out.record_reference = dict(out.sd1_record_reference)
            out.margin = out.sd1_margin
            out.draw_id = out.draw_id_sd1
        out._bound_L = record_bound_max_L(out.record_reference["completion_input_tick"], out.margin)
        return out

    @staticmethod
    def read_dir(directory: Path, *, clf: Optional[mcell.Classifier] = None, floor_min: Optional[float] = None) -> Tuple["Archive6", Dict[str, Any]]:   # type: ignore[override]
        """Load an archive directory (sd1's closing archive or an sd2 checkpoint) after verifying its manifest; the derived state is rebuilt."""
        a, meta = s2.Archive2.read_dir(directory, clf=clf, floor_min=floor_min)
        return Archive6.adopt(a), meta

    # -- persistence -----------------------------------------------------------------------------------------------------------------------

    def write_files(self, directory: Path, meta: Mapping[str, Any]) -> Dict[str, str]:
        begun = self.sd2_first_iteration is not None
        sess = {e.get("name"): e for e in self.events if e["ev"] == "session"}
        extra = dict(meta, archive6_contract=ARCHIVE6_CONTRACT, sd2_first_iteration=self.sd2_first_iteration,
                     draw_ids6={"rd1": self.archive_id, "rd2": self.draw_id_rd2, "rd3": self.draw_id_rd3, "rd4": self.draw_id_rd4, "sd1": self.draw_id_sd1, "sd2": self.draw_id_sd2 if begun else None},
                     select4_digest_sd1=(sess.get(SESSION_NAME_SD1) or {}).get("digest"), select4_digest_sd2=(sess.get(SESSION_NAME) or {}).get("digest"),
                     record_reference_sd1=dict(self.sd1_record_reference) if self.sd1_record_reference else None, record_reference_sd2=dict(self.record_reference) if begun else None,
                     margin_sd1=self.sd1_margin, margin_sd2=self.margin if begun else None,
                     bound_L_by_session={"sd1": self.sd1_bound_max_L() if self.sd1_record_reference else None, "sd2": self._bound_L if begun else None})
        # sd1's writer stores `record_reference` / `margin` / `select4_digest` = sd1's event's; here `record_reference` and `margin` are the CURRENT ones (sd2's once begun) while
        # `select4_digest` stays sd1's event's digest; `select4_digest_sd2`, `record_reference_sd2` and `bound_L_by_session` name sd2's unambiguously.
        return super().write_files(directory, extra)


# -- the ledger rebuild and audit (six parts) -----------------------------------------------------------------------------------------------


def rebuild6(saved: s2.Archive2, lines_sha256: str, on_dispatch: Optional[Callable[[Dict[str, Any]], None]] = None) -> Archive6:
    """Replay the ordered ledger over the stored bursts: rd1's part under v1, rd2's and rd3's under v2 (draw ids `_v2`, `_rd3`), rd4's under v3 (`_rd4`), sd1's `session` event and part
    under v4 at sd1's reference (`_sd1`, E7 at sd1's bound), sd2's `session` event and part under v4 at sd2's reference (`_sd2`, E7 at sd2's bound). Every selection is re-derived and
    every insert / replace / keep decision is re-checked. Zero native ticks."""
    if not saved.cells:
        raise march.ArchiveError("nothing to rebuild")
    out = Archive6(saved.archive_id, clf=saved.clf, floor_min=saved.floor_min)
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
            if on_dispatch is not None:
                on_dispatch(dispatch_row(out, chosen, ev["it"]))
            out.apply_dispatch(ev["it"], ev["cell"], ev["worker"])
        elif kind == "fail":
            out.note_failure(ev["it"], ev["why"])
        elif kind == "session":
            name = ev.get("name")
            if name == SESSION_NAME_RD2:
                made = out.begin_v2(int(ev["first_iteration"]), lines_sha256)
            elif name == SESSION_NAME_RD3:
                made = out.begin_rd3(int(ev["first_iteration"]), lines_sha256)
            elif name == SESSION_NAME_RD4:
                made = out.begin_rd4(int(ev["first_iteration"]), lines_sha256)
            elif name == SESSION_NAME_SD1:
                made = out.begin_sd1(int(ev["first_iteration"]), lines_sha256, ev["record_reference"], int(ev["margin"]))
            elif name == SESSION_NAME:
                made = out.begin_sd2(int(ev["first_iteration"]), lines_sha256, ev["record_reference"], int(ev["margin"]))
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


def audit6(saved: s2.Archive2, lines_sha256: str, *, collect_rows_from: Optional[int] = None) -> Dict[str, Any]:
    """The close audit of the six-part archive: the ledger rebuilds it exactly; every prefix reconstructs; the incremental derived state equals the first-principles recomputation; the
    dispatch iterations are strictly increasing and never reused; every session event precedes the dispatches of its part. With `collect_rows_from` the rebuild also returns the dispatch
    rows of every iteration from that one on (the readings), so the ledger is rebuilt once."""
    problems: List[str] = []
    rows: List[Dict[str, Any]] = []

    def hook(row: Dict[str, Any]) -> None:
        if collect_rows_from is not None and row["it"] >= collect_rows_from:
            rows.append(row)

    try:
        rebuilt = rebuild6(saved, lines_sha256, on_dispatch=hook if collect_rows_from is not None else None)
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
    except (march.ArchiveError, Select6Error, s5.Select5Error, s4.Select4Error, s3.Select3Error, s2.Select2Error, KeyError, IndexError, ValueError, TypeError) as exc:
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
    floor_it: Optional[int] = None
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
    return {"ok": not problems, "problems": problems[:20], "cells": len(saved.cells), "bursts": len(saved.bursts), "events": len(saved.events), "prefixes_reconstructed": lengths_ok,
            "dispatch_rows": rows}
