"""M8-sd1: the archive that continues rd4's closing archive (rd1 + rd2 + rd3 + rd4) under the selection `m8_rd_select_v4` (pure, stdlib only).

Design: docs/rl_m8_sd1_proposal_2026-10-07.md section 3, as decided on 2026-10-11 (length scale 120, margin 24, the record bound included, the harmonic level draw kept, the
reference fixed at the open, no special treatment of any family).

`m8_rd_select_v4` is `m8_rd_select_v3` with EXACTLY TWO registered changes, both generic time quantities in the archive's own units:

    (a) the length-factor scale: 120 (one explorer burst, m8_rd_explore.BURST_WORDS) instead of 900:
            w(c) = (1/sqrt(1+seen)) * 120 / (120 + L - L_min(level over eligible cells)) * w_res
    (b) E7, the record bound on eligibility: a cell is eligible only if L(c) + 1 <= T_rec - M, where T_rec is the archive's best VERIFIED clear (completion_input_tick, pinned
        at the open and never moved during the session) and M the registered margin. A prefix at least as long as the sought clear cannot shorten it. X1 does not exempt from E7.

Everything else is v3's, unchanged: eligibility E1-E6 and X1, the harmonic level weight 1 / (1 + top - level), the count term (1 + seen)^-1/2, the resource weights, replacement under
v2 doom, the descent tree, the recovery bound, the cell key `m8_rd_cell_v1`, the explorer `m8_rd_explore_v1` and the 120-word burst. The contract digest of v4 is built from v3's own
description with only the registered keys replaced or added (`select4_description`, `REGISTERED_CHANGES`); a test restores them and reproduces the real v3 digest.

`Archive5` extends rd4's `Archive4` (rl/m8_rd4_select.py, untouched) with a fifth session: a `session` event (name `sd1`) carrying v4's digest, the record reference and the margin,
whose draw suffix is `_sd1` and whose weights and eligibility are v4's from sd1's first iteration on. Iterations of rd1, rd2, rd3 and rd4 are selected under their own rules and draws,
so the whole history rebuilds (`rebuild5` / `audit5`, five parts). E7 is the first eligibility change across the parts of one ledger, so the eligible-levels cache is keyed on the mode
as well as on the archive version.

Nothing here reads a position, a surface, a target location, a target identity or a direction in a PREFERENCE (v2's property, kept): E7 reads a cell's L and the pinned reference.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import m8_rd_archive as march
import m8_rd_cells as mcell
import m8_rd_explore as mx
import m8_rd_select2 as s2
import m8_rd3_select as s3
import m8_rd4_select as s4

ARCHIVE5_CONTRACT = "m8_sd1_archive_v1"
SELECT4_CONTRACT = "m8_rd_select_v4"
SELECT3_CONTRACT = s4.SELECT3_CONTRACT
SESSION_NAME_RD2 = s4.SESSION_NAME_RD2             # "rd2"
SESSION_NAME_RD3 = s4.SESSION_NAME_RD3             # "rd3"
SESSION_NAME_RD4 = s4.SESSION_NAME                 # "rd4"
SESSION_NAME = "sd1"
DRAW_SUFFIX_RD2 = s4.DRAW_SUFFIX_RD2               # "_v2"
DRAW_SUFFIX_RD3 = s4.DRAW_SUFFIX_RD3               # "_rd3"
DRAW_SUFFIX_RD4 = s4.DRAW_SUFFIX                   # "_rd4"
DRAW_SUFFIX = "_sd1"
LENGTH_SCALE_V4 = float(mx.BURST_WORDS)            # 120: one explorer burst (registered; v3: 900)
# the keys of the contract description that differ between v3 and v4 (and no others)
REGISTERED_CHANGES = ("contract", "cell_weight", "length_scale", "eligibility", "draws", "record_reference", "margin")
CHANGES_TEXT = ["length_scale 900 -> 120", "eligibility + E7 (L + 1 <= T_rec - M)"]
RECORD_REFERENCE_KEYS = ("completion_input_tick", "completion_time_passed", "native_action_digest", "words", "cid", "iteration", "kind", "session", "source")
SESSIONS = ("rd1", "rd2", "rd3", "rd4", "sd1")


class Select5Error(RuntimeError):
    """A violated sd1 archive invariant (never silently tolerated)."""


# -- the contracts -------------------------------------------------------------------------------------------------------------------------


def record_reference_block(*, completion_input_tick: int, completion_time_passed: int, native_action_digest: str, words: int, cid: int, iteration: int, kind: str, session: str,
                           source: str) -> Dict[str, Any]:
    """The archive's best VERIFIED clear, as the selection and the rule read it: both completion clocks (never collapsed), the native action digest, the word count and where it comes
    from. Checked field by field."""
    rr = {"completion_input_tick": int(completion_input_tick), "completion_time_passed": int(completion_time_passed), "native_action_digest": str(native_action_digest), "words": int(words),
          "cid": int(cid), "iteration": int(iteration), "kind": str(kind), "session": str(session), "source": str(source)}
    validate_record_reference(rr)
    return rr


def validate_record_reference(rr: Mapping[str, Any]) -> None:
    if not isinstance(rr, Mapping) or set(rr) != set(RECORD_REFERENCE_KEYS):
        raise Select5Error(f"a record reference carries exactly {sorted(RECORD_REFERENCE_KEYS)}, got {sorted(rr) if isinstance(rr, Mapping) else type(rr).__name__}")
    for k in ("completion_input_tick", "completion_time_passed", "words", "cid", "iteration"):
        if not isinstance(rr[k], int) or isinstance(rr[k], bool) or rr[k] < 0:
            raise Select5Error(f"record reference {k} is not a non-negative integer: {rr[k]!r}")
    if rr["completion_input_tick"] <= 0 or rr["completion_input_tick"] != rr["words"]:
        raise Select5Error("the record's completion_input_tick must be positive and equal to its word count (one submitted word per consumed tick)")
    d = rr["native_action_digest"]
    if not (isinstance(d, str) and len(d) == 64 and all(c in "0123456789abcdef" for c in d)):
        raise Select5Error("the record's native action digest is not a 64-hex sha256")
    for k in ("kind", "session", "source"):
        if not isinstance(rr[k], str) or not rr[k]:
            raise Select5Error(f"record reference {k} is not a non-empty string")


def record_bound_max_L(t_rec: int, margin: int) -> int:
    """E7: a cell is eligible only if L + 1 <= T_rec - M, i.e. L <= T_rec - M - 1."""
    return int(t_rec) - int(margin) - 1


def select4_description(status_table_sha256: str, lines_sha256: str, floor_min: Optional[float] = None, record_reference: Optional[Mapping[str, Any]] = None,
                        margin: int = 0) -> Dict[str, Any]:
    """v4's contract description: v3's with the registered changes (REGISTERED_CHANGES) and no other. `record_reference` and `margin` are the session's pinned constants."""
    if record_reference is None:
        raise Select5Error("v4's description needs the record reference")
    validate_record_reference(record_reference)
    if not isinstance(margin, int) or isinstance(margin, bool) or margin < 1:
        raise Select5Error(f"the margin is a positive integer number of ticks, got {margin!r}")
    d = s4.select3_description(status_table_sha256, lines_sha256, floor_min)
    d["contract"] = SELECT4_CONTRACT
    d["cell_weight"] = "(1/sqrt(1+seen)) * 120 / (120 + L - L_min(level over eligible cells)) * w_res"
    d["length_scale"] = LENGTH_SCALE_V4
    d["eligibility"] = list(d["eligibility"]) + ["E7 record bound: L + 1 <= T_rec - M (T_rec = the archive's best verified completion_input_tick, pinned at the open and never moved "
                                                 "during the session; M = the registered margin); X1 does not exempt from E7; cell 0 stays always eligible"]
    d["draws"] = (f"two uniforms from sha256(m8_rd|<archive id>{DRAW_SUFFIX}|select|<iteration>), cells in id order; the explorer draws "
                  f"use the same id in m8_rd|<archive id>{DRAW_SUFFIX}|explore|<iteration>|<decision index>")
    d["record_reference"] = dict(record_reference)
    d["margin"] = int(margin)
    return d


def select4_contract_digest(status_table_sha256: str, lines_sha256: str, floor_min: Optional[float] = None, record_reference: Optional[Mapping[str, Any]] = None, margin: int = 0) -> str:
    return hashlib.sha256(json.dumps(select4_description(status_table_sha256, lines_sha256, floor_min, record_reference, margin), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def changed_keys(status_table_sha256: str, lines_sha256: str, floor_min: Optional[float], record_reference: Mapping[str, Any], margin: int) -> List[str]:
    """The description keys that differ between v3 and v4 (the registered changes, nothing else)."""
    a = s4.select3_description(status_table_sha256, lines_sha256, floor_min)
    b = select4_description(status_table_sha256, lines_sha256, floor_min, record_reference, margin)
    return sorted({k for k in set(a) | set(b) if a.get(k) != b.get(k)})


def restore_v3(description: Mapping[str, Any], status_table_sha256: str, lines_sha256: str, floor_min: Optional[float] = None) -> Dict[str, Any]:
    """v4's description with the registered keys restored to v3's values (the proof that nothing else differs)."""
    v3 = s4.select3_description(status_table_sha256, lines_sha256, floor_min)
    d = dict(description)
    for k in REGISTERED_CHANGES:
        if k in v3:
            d[k] = v3[k]
        else:
            d.pop(k, None)
    return d


def draws_description() -> Dict[str, Any]:
    return {"select": f"m8_rd|<archive id>{DRAW_SUFFIX}|select|<iteration>", "explore": f"m8_rd|<archive id>{DRAW_SUFFIX}|explore|<iteration>|<decision index>",
            "identity_open": "m8_rd|<archive id>|identity_open|sd1|<cell id>", "identity_close": "m8_rd|<archive id>|identity_close|sd1|<cell id>",
            "rd4_select": f"m8_rd|<archive id>{DRAW_SUFFIX_RD4}|select|<iteration>", "rd3_select": f"m8_rd|<archive id>{DRAW_SUFFIX_RD3}|select|<iteration>",
            "rd2_select": f"m8_rd|<archive id>{DRAW_SUFFIX_RD2}|select|<iteration>", "rd1_select": "m8_rd|<archive id>|select|<iteration>"}


def draws_digest() -> str:
    return hashlib.sha256(json.dumps(draws_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def v4_weights(cells: Sequence[march.Cell]) -> List[float]:
    """The v4 cell weights of the eligible cells of one level: count term (v3's) x length factor at scale 120 x resource weight."""
    lmin = min(c.L for c in cells)
    return [(1.0 / math.sqrt(1 + c.seen)) * (LENGTH_SCALE_V4 / (LENGTH_SCALE_V4 + c.L - lmin)) * s2.W_RES[c.key[2]] for c in cells]


# -- the archive -----------------------------------------------------------------------------------------------------------------------------


class Archive5(s4.Archive4):
    """rd4's archive plus sd1's session: its draw id by iteration, v4's weights and the record bound from sd1's first iteration on."""

    def __init__(self, archive_id: str, *, clf: Optional[mcell.Classifier] = None, floor_min: Optional[float] = None):
        super().__init__(archive_id, clf=clf, floor_min=floor_min)
        self.draw_id_sd1 = str(archive_id) + DRAW_SUFFIX
        self.sd1_first_iteration: Optional[int] = None
        self.record_reference: Optional[Dict[str, Any]] = None
        self.margin: Optional[int] = None
        self._bound_L: Optional[int] = None
        self._v4 = False                            # True while the weights and the eligibility are v4's (set per selection by the iteration, by `probabilities`, and by `as_v4`)
        self._elig5: Optional[Tuple[Tuple[int, bool], Dict[int, List[march.Cell]]]] = None

    # -- the draw id, the weights, the eligibility -------------------------------------------------------------------------------------

    def draw_for(self, iteration: int) -> str:
        if self.sd1_first_iteration is not None and int(iteration) >= self.sd1_first_iteration:
            return self.draw_id_sd1
        return super().draw_for(iteration)

    def v4_for(self, iteration: int) -> bool:
        return self.sd1_first_iteration is not None and int(iteration) >= self.sd1_first_iteration

    def bound_max_L(self) -> int:
        if self._bound_L is None:
            raise Select5Error("the record bound is not set (sd1 has not begun)")
        return self._bound_L

    def eligible(self, c: march.Cell) -> bool:                       # type: ignore[override]
        if not super().eligible(c):
            return False
        if self._v4 and c.id != 0 and c.L > self.bound_max_L():
            return False
        return True

    def eligible_levels(self) -> Dict[int, List[march.Cell]]:       # type: ignore[override]
        """The base cache is keyed on the archive version alone; E7 changes the eligible set between a v3 iteration and a v4 iteration of the same archive, so the key carries the mode."""
        key = (self._version, bool(self._v4))
        if self._elig5 is not None and self._elig5[0] == key:
            return self._elig5[1]
        out: Dict[int, List[march.Cell]] = {}
        for lv, cs in self._level_cells.items():
            e = [c for c in cs if self.eligible(c)]
            if e:
                out[lv] = e
        self._elig5 = (key, out)
        return out

    def cell_weights(self, cells: Sequence[march.Cell]) -> List[float]:
        if self._v4:
            return v4_weights(cells)
        return super().cell_weights(cells)

    def select(self, iteration: int) -> march.Cell:
        keep = self._v4
        self._v4 = self.v4_for(iteration)
        try:
            return super().select(iteration)         # rd4's weight switch, rd3's draw-id wrapper, rd2's selection, with this iteration's eligibility and weights
        finally:
            self._v4 = keep

    @contextlib.contextmanager
    def as_v4(self) -> Iterator["Archive5"]:
        """Evaluate eligibility (E7 included) and weights as v4's inside the block (stats, overlays, identity samples), whatever the flags were before."""
        keep3, keep4 = self._v3, self._v4
        self._v3, self._v4 = True, True
        try:
            yield self
        finally:
            self._v3, self._v4 = keep3, keep4

    def probabilities(self, mode: Optional[str] = None) -> Dict[int, float]:
        """The analytic selection probability of every eligible cell. `mode` None = the current rules (v4 once sd1 has begun, v3 after rd4, v2 before); "v2" / "v3" / "v4" evaluate that rule
        on the same archive (the counterfactual readings of the reports; v4 needs the record bound)."""
        if mode not in (None, "v2", "v3", "v4"):
            raise Select5Error(f"unknown mode {mode!r}")
        keep3, keep4 = self._v3, self._v4
        if mode is None:
            self._v4 = self.sd1_first_iteration is not None
            self._v3 = self.rd4_first_iteration is not None
        else:
            self._v4 = mode == "v4"
            self._v3 = mode in ("v3", "v4")
        if self._v4 and self._bound_L is None:
            self._v3, self._v4 = keep3, keep4
            raise Select5Error("v4 probabilities need the record bound (sd1 has not begun)")
        try:
            return s2.Archive2.probabilities(self)
        finally:
            self._v3, self._v4 = keep3, keep4

    # -- the session switch --------------------------------------------------------------------------------------------------------------

    def begin_sd1(self, first_iteration: int, lines_sha256: str, record_reference: Mapping[str, Any], margin: int) -> Dict[str, Any]:
        """Add sd1's `session` event. v2's digest, recomputed from the current contract, must equal rd2's and rd3's session digests and v3's must equal rd4's (the earlier sessions ran
        unchanged); sd1's own event carries v4's digest, the record reference and the margin, with v3's digest recorded beside it."""
        if self.mode != 2 or self.rd2_first_iteration is None or self.rd3_first_iteration is None or self.rd4_first_iteration is None:
            raise Select5Error("sd1 begins only after rd2's, rd3's and rd4's session events")
        if self.sd1_first_iteration is not None:
            raise Select5Error("sd1 has already begun")
        if self._pending:
            raise Select5Error(f"{len(self._pending)} dispatched iterations are still pending")
        sess = [e for e in self.events if e["ev"] == "session"]
        if [e.get("name") for e in sess] != [SESSION_NAME_RD2, SESSION_NAME_RD3, SESSION_NAME_RD4]:
            raise Select5Error(f"session events before sd1: {[e.get('name') for e in sess]}")
        prior = [e["it"] for e in self.events if e["ev"] == "dispatch"]
        if prior and int(first_iteration) <= max(prior):
            raise Select5Error(f"first iteration {first_iteration} would reuse iteration {max(prior)}")
        validate_record_reference(record_reference)
        if not isinstance(margin, int) or isinstance(margin, bool) or margin < 1:
            raise Select5Error(f"the margin is a positive integer number of ticks, got {margin!r}")
        v2 = s2.select2_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min)
        if sess[0]["digest"] != v2 or sess[1]["digest"] != v2:
            raise Select5Error("the selection contract digest differs from rd2's and rd3's session events (they ran m8_rd_select_v2 unchanged): this is not a continuation of that history")
        v3 = s4.select3_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min)
        if sess[2]["digest"] != v3:
            raise Select5Error("the v3 selection contract digest differs from rd4's session event (rd4 ran m8_rd_select_v3 unchanged): this is not a continuation of that history")
        rr = dict(record_reference)
        v4 = select4_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min, rr, int(margin))
        ev = {"ev": "session", "name": SESSION_NAME, "select": SELECT4_CONTRACT, "digest": v4, "first_iteration": int(first_iteration), "draw_suffix": DRAW_SUFFIX,
              "changed_from": {"select": SELECT3_CONTRACT, "digest": v3, "changes": list(CHANGES_TEXT)},
              "record_reference": rr, "margin": int(margin), "length_scale": LENGTH_SCALE_V4}
        self.events.append(ev)
        self.sd1_first_iteration = int(first_iteration)
        self.first_iteration = int(first_iteration)
        self.draw_id = self.draw_id_sd1
        self.record_reference = rr
        self.margin = int(margin)
        self._bound_L = record_bound_max_L(rr["completion_input_tick"], int(margin))
        self._version += 1
        return ev

    # -- ranges of the five parts --------------------------------------------------------------------------------------------------------

    def iteration_ranges(self) -> Dict[str, Tuple[Optional[int], Optional[int]]]:                  # type: ignore[override]
        its = sorted(e["it"] for e in self.events if e["ev"] == "dispatch")
        firsts = [self.rd2_first_iteration, self.rd3_first_iteration, self.rd4_first_iteration, self.sd1_first_iteration]
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
        for name, first in (("rd2", self.rd2_first_iteration), ("rd3", self.rd3_first_iteration), ("rd4", self.rd4_first_iteration), ("sd1", self.sd1_first_iteration)):
            if first is not None and int(iteration) >= first:
                out = name
        return out

    # -- construction from an rd2-readable archive -----------------------------------------------------------------------------------------

    @classmethod
    def adopt(cls, a: s2.Archive2) -> "Archive5":                    # type: ignore[override]
        """The same archive state as `a` (rd2's loader did the work), as an Archive5. Requires rd2's, rd3's and rd4's session events, and sd1's if present."""
        out = cls.__new__(cls)
        out.__dict__.update(a.__dict__)
        out.draw_id_rd2 = str(out.archive_id) + DRAW_SUFFIX_RD2
        out.draw_id_rd3 = str(out.archive_id) + DRAW_SUFFIX_RD3
        out.draw_id_rd4 = str(out.archive_id) + DRAW_SUFFIX_RD4
        out.draw_id_sd1 = str(out.archive_id) + DRAW_SUFFIX
        out._v3 = False
        out._v4 = False
        out._elig5 = None
        out.record_reference = None
        out.margin = None
        out._bound_L = None
        sess = [e for e in out.events if e["ev"] == "session"]
        names = [e.get("name") for e in sess]
        if names not in ([SESSION_NAME_RD2, SESSION_NAME_RD3, SESSION_NAME_RD4], [SESSION_NAME_RD2, SESSION_NAME_RD3, SESSION_NAME_RD4, SESSION_NAME]):
            raise Select5Error(f"session events {names}: an sd1 archive carries rd2's, rd3's and rd4's and at most sd1's")
        out.rd2_first_iteration = int(sess[0]["first_iteration"])
        out.rd3_first_iteration = int(sess[1]["first_iteration"])
        out.rd4_first_iteration = int(sess[2]["first_iteration"])
        if len(sess) == 4:
            ev = sess[3]
            out.sd1_first_iteration = int(ev["first_iteration"])
            validate_record_reference(ev["record_reference"])
            out.record_reference = dict(ev["record_reference"])
            out.margin = int(ev["margin"])
            out._bound_L = record_bound_max_L(out.record_reference["completion_input_tick"], out.margin)
            out.draw_id = out.draw_id_sd1
        else:
            out.sd1_first_iteration = None
            out.draw_id = out.draw_id_rd4
        return out

    @staticmethod
    def read_dir(directory: Path, *, clf: Optional[mcell.Classifier] = None, floor_min: Optional[float] = None) -> Tuple["Archive5", Dict[str, Any]]:   # type: ignore[override]
        """Load an archive directory (rd4's closing archive or an sd1 checkpoint) after verifying its manifest; the derived state is rebuilt."""
        a, meta = s2.Archive2.read_dir(directory, clf=clf, floor_min=floor_min)
        return Archive5.adopt(a), meta

    # -- persistence -----------------------------------------------------------------------------------------------------------------------

    def write_files(self, directory: Path, meta: Mapping[str, Any]) -> Dict[str, str]:
        begun = self.sd1_first_iteration is not None
        extra = dict(meta, archive5_contract=ARCHIVE5_CONTRACT, sd1_first_iteration=self.sd1_first_iteration,
                     draw_ids5={"rd1": self.archive_id, "rd2": self.draw_id_rd2, "rd3": self.draw_id_rd3, "rd4": self.draw_id_rd4, "sd1": self.draw_id_sd1 if begun else None},
                     select4_contract=SELECT4_CONTRACT if begun else None,
                     select4_digest=next((e["digest"] for e in self.events if e["ev"] == "session" and e.get("name") == SESSION_NAME), None),
                     record_reference=dict(self.record_reference) if begun else None, margin=self.margin, length_scale_v4=LENGTH_SCALE_V4 if begun else None)
        # rd2's writer stores `select2_digest` = the LAST session event's digest (here v4's); rd4's `select3_digest` names rd4's own; `select4_digest` names sd1's unambiguously.
        return super().write_files(directory, extra)


# -- the ledger rebuild and audit (five parts) -----------------------------------------------------------------------------------------------


dispatch_row = s4.dispatch_row                     # the start cell's state AT DISPATCH; `created_in` reads Archive5.session_of_iteration, so sd1 cells are named


def rebuild5(saved: s2.Archive2, lines_sha256: str, on_dispatch: Optional[Callable[[Dict[str, Any]], None]] = None) -> Archive5:
    """Replay the ordered ledger over the stored bursts: rd1's part under v1, rd2's and rd3's under v2 (draw ids `_v2`, `_rd3`), rd4's under v3 (`_rd4`), sd1's `session` event and part
    under v4 (`_sd1`, E7 and the scale 120). Every selection is re-derived and every insert / replace / keep decision is re-checked. Zero native ticks."""
    if not saved.cells:
        raise march.ArchiveError("nothing to rebuild")
    out = Archive5(saved.archive_id, clf=saved.clf, floor_min=saved.floor_min)
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
            elif name == SESSION_NAME:
                made = out.begin_sd1(int(ev["first_iteration"]), lines_sha256, ev["record_reference"], int(ev["margin"]))
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


def audit5(saved: s2.Archive2, lines_sha256: str, *, collect_rows_from: Optional[int] = None) -> Dict[str, Any]:
    """The close audit of the five-part archive: the ledger rebuilds it exactly; every prefix reconstructs; the incremental derived state equals the first-principles recomputation; the
    dispatch iterations are strictly increasing and never reused; every session event precedes the dispatches of its part. With `collect_rows_from` the rebuild also returns the dispatch
    rows of every iteration from that one on (the readings), so the ledger is rebuilt once."""
    problems: List[str] = []
    rows: List[Dict[str, Any]] = []

    def hook(row: Dict[str, Any]) -> None:
        if collect_rows_from is not None and row["it"] >= collect_rows_from:
            rows.append(row)

    try:
        rebuilt = rebuild5(saved, lines_sha256, on_dispatch=hook if collect_rows_from is not None else None)
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
    except (march.ArchiveError, Select5Error, s4.Select4Error, s3.Select3Error, s2.Select2Error, KeyError, IndexError, ValueError, TypeError) as exc:
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


# -- the overlays ----------------------------------------------------------------------------------------------------------------------------------


def overlay_rows5(a: s2.Archive2, t_rec: int, margin: int, desc: Optional[Sequence[bool]] = None, bound: Optional[Sequence[bool]] = None) -> List[Dict[str, Any]]:
    """v2's overlay rows (E1-E6, X1 with reason codes) plus E7's reason code `record_bound` (L + 1 > T_rec - M). Derived, recorded at the open with a digest, recomputed at the close."""
    rows = s2.overlay_rows(a, desc, bound)
    b = record_bound_max_L(t_rec, margin)
    for c, r in zip(a.cells, rows):
        if c.id != 0 and c.L > b:
            r["reasons"] = list(r["reasons"]) + ["record_bound"]
            r["eligible"] = False
    return rows


overlay_bytes5 = s2.overlay_bytes


def overlay_counts5(a: s2.Archive2, rows: Sequence[Mapping[str, Any]], t_rec: int, margin: int) -> Dict[str, Any]:
    """v2's overlay figures (unchanged by E7's reason code) plus the record bound's: the cells it excludes in all, among the cells eligible under v3, by level, and the v4-eligible count."""
    out = dict(s2.overlay_counts(a, rows))
    by = {c.id: r for c, r in zip(a.cells, rows)}
    rb = [c for c in a.cells if "record_bound" in by[c.id]["reasons"]]
    v3_eligible = [c for c in a.cells if c.id == 0 or not [x for x in by[c.id]["reasons"] if x != "record_bound"]]
    v3_ids = {c.id for c in v3_eligible}
    rb_v3 = [c for c in rb if c.id in v3_ids]
    levels = sorted({c.level for c in a.cells})
    out.update({"bound_L": record_bound_max_L(t_rec, margin), "record_reference_completion_input_tick": int(t_rec), "margin": int(margin),
                "record_bound_cells": len(rb), "record_bound_among_v3_eligible": len(rb_v3),
                "record_bound_by_level": {str(lv): sum(1 for c in rb if c.level == lv) for lv in levels},
                "record_bound_among_v3_eligible_by_level": {str(lv): sum(1 for c in rb_v3 if c.level == lv) for lv in levels},
                "eligible_v3": len(v3_eligible), "eligible_v4": sum(1 for r in rows if r["eligible"]),
                "eligible_v4_by_level": {str(lv): sum(1 for c in a.cells if c.level == lv and by[c.id]["eligible"]) for lv in levels},
                "shortest_L_by_level": {str(lv): min(c.L for c in a.cells if c.level == lv) for lv in levels},
                "shortest_eligible_L_by_level": {str(lv): min((c.L for c in a.cells if c.level == lv and by[c.id]["eligible"]), default=None) for lv in levels}})
    return out
