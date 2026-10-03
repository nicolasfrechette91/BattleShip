"""M8-rd4: the archive that continues rd3's closing archive (rd1 + rd2 + rd3) under the revised selection `m8_rd_select_v3` (pure, stdlib only).

Design: docs/rl_m8_rd3_stop_review_2026-10-03.md (the K1 candidate, section 2.2) as decided in docs/rl_m8_rd4_decisions_2026-10-03.md (decisions 2 and 3, the mechanical readings).

`m8_rd_select_v3` is `m8_rd_select_v2` with EXACTLY ONE change: the novelty term of the cell weight. v2 used

    (1/sqrt(1 + chosen) + 1/sqrt(1 + seen))  *  900 / (900 + L - L_min(level))  *  w_res

and v3 uses the published single-counter count score of Go-Explore (Ecoffet et al., Nature 590, 2021: W = 1/sqrt(C_seen + 1), exponent 1/2)

    (1/sqrt(1 + seen))                       *  900 / (900 + L - L_min(level))  *  w_res

Everything else is v2's, unchanged: eligibility E1-E6 and X1, the harmonic level weight 1 / (1 + top - level), the length factor, the resource weight, replacement under v2 doom,
the descent tree, the recovery bound, the cell key `m8_rd_cell_v1`, the explorer `m8_rd_explore_v1` and the 120-word burst. The contract digest of v3 is built from v2's own description with
only the declared keys replaced (`select3_description`); `REGISTERED_CHANGES` names them and a test enforces that no other key differs.

`Archive4` extends rd3's `Archive3` (rl/m8_rd3_select.py, untouched) with a third session: a `session` event (name `rd4`) whose digest is v3's, whose draw suffix is rd4-specific (`_rd4`) and
whose weights are v3's from rd4's first iteration on; iterations of rd1, rd2 and rd3 are selected under their own rules and draws (so the ledger of the whole history rebuilds), and
`rebuild4` / `audit4` replay all four parts. `rebuild4` can report, for every dispatch, the start cell's counters AT DISPATCH (the mechanism check of decision 7 reads them).

Nothing here reads a position, a surface, a target location or a direction in a PREFERENCE (v2's property, kept).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import m8_rd_archive as march
import m8_rd_cells as mcell
import m8_rd_select2 as s2
import m8_rd3_select as s3

ARCHIVE4_CONTRACT = "m8_rd4_archive_v1"
SELECT3_CONTRACT = "m8_rd_select_v3"
SELECT2_CONTRACT = s2.SELECT2_CONTRACT
SESSION_NAME_RD2 = s3.SESSION_NAME_RD2             # "rd2"
SESSION_NAME_RD3 = s3.SESSION_NAME                 # "rd3"
SESSION_NAME = "rd4"
DRAW_SUFFIX_RD2 = s3.DRAW_SUFFIX_RD2               # "_v2"
DRAW_SUFFIX_RD3 = s3.DRAW_SUFFIX                   # "_rd3"
DRAW_SUFFIX = "_rd4"
COUNT_EXPONENT = 0.5                               # the published exponent (decision 2): not tuned; `v3_weights` computes it as 1 / sqrt(1 + seen)
# the keys of the contract description that differ between v2 and v3 (and no others)
REGISTERED_CHANGES = ("contract", "cell_weight", "count_term", "draws")


class Select4Error(RuntimeError):
    """A violated rd4 archive invariant (never silently tolerated)."""


# -- the contracts -------------------------------------------------------------------------------------------------------------------------


def select2_description(status_table_sha256: str, lines_sha256: str, floor_min: Optional[float] = None) -> Dict[str, Any]:
    """v2's contract description, key for key as `m8_rd_select2.select2_contract_digest` hashes it (a replica: that function builds the dict inline). `v2_replica_ok` proves the equality."""
    return {"contract": s2.SELECT2_CONTRACT,
            "eligibility": ["E1 resource class != X", "E2 the representative did not end the episode at L", f"E3 L <= {march.MAX_ELIGIBLE_L}",
                            "E4 not doomed under v1 (the stored 60-tick flag)", "E5 not descent-doomed (burst tree)",
                            "E6 not bound-unrecoverable", "X1 exactly one live target: exempt from E4-E6", "cell 0 always eligible"],
            "level": "weight 1 / (1 + top - level) over the levels that have eligible cells",
            "cell_weight": "(1/sqrt(1+chosen) + 1/sqrt(1+seen)) * 900 / (900 + L - L_min(level over eligible cells)) * w_res",
            "w_res": s2.W_RES, "length_scale": march.LENGTH_SCALE, "doom_window": march.DOOM_WINDOW,
            "descent_doom": "airborne reach (b, o) doomed iff no continuation reached a grounded REACH and a continuation ended in a native "
                            "fall; continuations = the rest of burst b after o and, recursively, every burst whose pinned start "
                            "representative is (b, o') with o' >= o; a later landing clears the doom; grounded evidence = grounded "
                            "reaches for every burst",
            "bound": {"rule": "y + R + margin < Y_floor_min", "margin": s2.BOUND_MARGIN, "gravity": s2.GRAVITY, "aerial_jump": s2.RISE_AERIAL_JUMP,
                      "upb": s2.RISE_UPB, "tornado": s2.RISE_TORNADO, "ballistic": "max(v,0)^2/(2g) + max(v,0)",
                      "classes": {"A2": "B + T + J + U", "A1": "B + T + U", "A0 special_hi": "B + U", "A0 helpless": "B"},
                      "tornado_unspent_assumed": True, "y_floor_min": s2.y_floor_min() if floor_min is None else float(floor_min),
                      "lines_sha256": lines_sha256},
            "replacement": "doom := (E4 or E5 or E6) and not X1, evaluated for the incumbent at the time of the reach and for the new reach "
                           "from its own burst (E5) and its own end record (E6); a non-doomed reach beats a doomed one, then the "
                           "strictly shorter L; ties keep the incumbent",
            "draws": f"two uniforms from sha256(m8_rd|<archive id>{s2.DRAW_SUFFIX}|select|<iteration>), cells in id order; the explorer draws "
                     f"use the same id in m8_rd|<archive id>{s2.DRAW_SUFFIX}|explore|<iteration>|<decision index>",
            "status_table_sha256": status_table_sha256, "reads_position_in_preference": False}


def v2_replica_ok(status_table_sha256: str, lines_sha256: str, floor_min: Optional[float] = None) -> bool:
    """The replica of v2's description hashes exactly like v2's own digest (so v3's description is v2's with the registered changes and nothing else)."""
    d = select2_description(status_table_sha256, lines_sha256, floor_min)
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest() == s2.select2_contract_digest(status_table_sha256, lines_sha256, floor_min)


def select3_description(status_table_sha256: str, lines_sha256: str, floor_min: Optional[float] = None) -> Dict[str, Any]:
    """v3's contract description: v2's with the registered changes (REGISTERED_CHANGES) and no other."""
    d = select2_description(status_table_sha256, lines_sha256, floor_min)
    d["contract"] = SELECT3_CONTRACT
    d["cell_weight"] = "(1/sqrt(1+seen)) * 900 / (900 + L - L_min(level over eligible cells)) * w_res"
    d["count_term"] = {"v2": "1/sqrt(1+chosen) + 1/sqrt(1+seen)", "v3": "1/sqrt(1+seen)", "exponent": COUNT_EXPONENT,
                       "seen": "bursts in which the cell was visited (Go-Explore's C_seen, increased once per exploration step however often the cell is visited in it)",
                       "source": "Ecoffet et al., First return, then explore, Nature 590 (2021), Methods and Extended Data Table 1: W = 1 / sqrt(C_seen + 1)",
                       "tuned": False}
    d["draws"] = (f"two uniforms from sha256(m8_rd|<archive id>{DRAW_SUFFIX}|select|<iteration>), cells in id order; the explorer draws "
                  f"use the same id in m8_rd|<archive id>{DRAW_SUFFIX}|explore|<iteration>|<decision index>")
    return d


def select3_contract_digest(status_table_sha256: str, lines_sha256: str, floor_min: Optional[float] = None) -> str:
    return hashlib.sha256(json.dumps(select3_description(status_table_sha256, lines_sha256, floor_min), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def changed_keys(status_table_sha256: str, lines_sha256: str, floor_min: Optional[float] = None) -> List[str]:
    """The description keys that differ between v2 and v3 (the registered changes, and the new `count_term` explanation key)."""
    a = select2_description(status_table_sha256, lines_sha256, floor_min)
    b = select3_description(status_table_sha256, lines_sha256, floor_min)
    return sorted({k for k in set(a) | set(b) if a.get(k) != b.get(k)})


def draws_description() -> Dict[str, Any]:
    return {"select": f"m8_rd|<archive id>{DRAW_SUFFIX}|select|<iteration>", "explore": f"m8_rd|<archive id>{DRAW_SUFFIX}|explore|<iteration>|<decision index>",
            "identity_open": "m8_rd|<archive id>|identity_open|rd4|<cell id>", "identity_close": "m8_rd|<archive id>|identity_close|rd4|<cell id>",
            "rd3_select": f"m8_rd|<archive id>{DRAW_SUFFIX_RD3}|select|<iteration>", "rd2_select": f"m8_rd|<archive id>{DRAW_SUFFIX_RD2}|select|<iteration>",
            "rd1_select": "m8_rd|<archive id>|select|<iteration>"}


def draws_digest() -> str:
    return hashlib.sha256(json.dumps(draws_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def v3_weights(cells: Sequence[march.Cell]) -> List[float]:
    """The v3 cell weights of the eligible cells of one level: count term x length factor x resource weight."""
    lmin = min(c.L for c in cells)
    return [(1.0 / math.sqrt(1 + c.seen)) * (march.LENGTH_SCALE / (march.LENGTH_SCALE + c.L - lmin)) * s2.W_RES[c.key[2]] for c in cells]


# -- the archive -----------------------------------------------------------------------------------------------------------------------------


class Archive4(s3.Archive3):
    """rd3's archive plus rd4's session: its draw id by iteration and its v3 cell weights from rd4's first iteration on."""

    def __init__(self, archive_id: str, *, clf: Optional[mcell.Classifier] = None, floor_min: Optional[float] = None):
        super().__init__(archive_id, clf=clf, floor_min=floor_min)
        self.draw_id_rd4 = str(archive_id) + DRAW_SUFFIX
        self.rd4_first_iteration: Optional[int] = None
        self._v3 = False                            # True while the weights are v3's (set per selection by the iteration, and by `probabilities`)

    # -- the draw id and the weights -------------------------------------------------------------------------------------------------

    def draw_for(self, iteration: int) -> str:
        """rd4's draw id from rd4's first iteration on, rd3's and rd2's before (the id the explorer and the selection key use)."""
        if self.rd4_first_iteration is not None and int(iteration) >= self.rd4_first_iteration:
            return self.draw_id_rd4
        return super().draw_for(iteration)

    def v3_for(self, iteration: int) -> bool:
        return self.rd4_first_iteration is not None and int(iteration) >= self.rd4_first_iteration

    def cell_weights(self, cells: Sequence[march.Cell]) -> List[float]:
        if self._v3:
            return v3_weights(cells)
        return super().cell_weights(cells)

    def select(self, iteration: int) -> march.Cell:
        keep = self._v3
        self._v3 = self.v3_for(iteration)
        try:
            return super().select(iteration)         # rd3's draw-id wrapper around rd2's selection, with this iteration's weights
        finally:
            self._v3 = keep

    def probabilities(self, mode: Optional[str] = None) -> Dict[int, float]:
        """The analytic selection probability of every eligible cell. `mode` None = the current rules (v3 once rd4 has begun, v2 before); "v2" / "v3" evaluate that rule on the same archive
        (the counterfactual readings of the reports)."""
        if mode not in (None, "v2", "v3"):
            raise Select4Error(f"unknown mode {mode!r}")
        keep = self._v3
        self._v3 = (self.rd4_first_iteration is not None) if mode is None else (mode == "v3")
        try:
            return super().probabilities()
        finally:
            self._v3 = keep

    # -- the session switch --------------------------------------------------------------------------------------------------------------

    def begin_rd4(self, first_iteration: int, lines_sha256: str) -> Dict[str, Any]:
        """Add rd4's `session` event. v2's digest, recomputed from the current contract, must equal the digests of rd2's and rd3's session events (the earlier sessions ran v2, unchanged);
        rd4's own event carries v3's digest, with v2's recorded beside it."""
        if self.mode != 2 or self.rd2_first_iteration is None or self.rd3_first_iteration is None:
            raise Select4Error("rd4 begins only after rd2's and rd3's session events")
        if self.rd4_first_iteration is not None:
            raise Select4Error("rd4 has already begun")
        if self._pending:
            raise Select4Error(f"{len(self._pending)} dispatched iterations are still pending")
        sess = [e for e in self.events if e["ev"] == "session"]
        if [e.get("name") for e in sess] != [SESSION_NAME_RD2, SESSION_NAME_RD3]:
            raise Select4Error(f"session events before rd4: {[e.get('name') for e in sess]}")
        prior = [e["it"] for e in self.events if e["ev"] == "dispatch"]
        if prior and int(first_iteration) <= max(prior):
            raise Select4Error(f"first iteration {first_iteration} would reuse iteration {max(prior)}")
        v2 = s2.select2_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min)
        if sess[0]["digest"] != v2 or sess[1]["digest"] != v2:
            raise Select4Error("the selection contract digest differs from the earlier sessions' (rd2 and rd3 ran m8_rd_select_v2 unchanged): this is not a continuation of that history")
        v3 = select3_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min)
        ev = {"ev": "session", "name": SESSION_NAME, "select": SELECT3_CONTRACT, "digest": v3, "first_iteration": int(first_iteration), "draw_suffix": DRAW_SUFFIX,
              "changed_from": {"select": SELECT2_CONTRACT, "digest": v2, "change": "cell weight count term: (1 + seen)^-1/2 replaces (1 + chosen)^-1/2 + (1 + seen)^-1/2"}}
        self.events.append(ev)
        self.rd4_first_iteration = int(first_iteration)
        self.first_iteration = int(first_iteration)
        self.draw_id = self.draw_id_rd4
        self._version += 1
        return ev

    # -- ranges of the four parts --------------------------------------------------------------------------------------------------------

    def iteration_ranges(self) -> Dict[str, Tuple[Optional[int], Optional[int]]]:                  # type: ignore[override]
        """(first, last) dispatch iteration of rd1, rd2, rd3 and rd4 (None where a part has none)."""
        its = sorted(e["it"] for e in self.events if e["ev"] == "dispatch")
        r2, r3, r4 = self.rd2_first_iteration, self.rd3_first_iteration, self.rd4_first_iteration
        p1 = [i for i in its if r2 is None or i < r2]
        p2 = [i for i in its if r2 is not None and i >= r2 and (r3 is None or i < r3)]
        p3 = [i for i in its if r3 is not None and i >= r3 and (r4 is None or i < r4)]
        p4 = [i for i in its if r4 is not None and i >= r4]
        rng = lambda xs: (xs[0], xs[-1]) if xs else (None, None)      # noqa: E731
        return {"rd1": rng(p1), "rd2": rng(p2), "rd3": rng(p3), "rd4": rng(p4)}

    def session_of_iteration(self, iteration: int) -> str:
        """The session an iteration number belongs to, by the sessions' first iterations (O(1); rd1 before rd2's first iteration)."""
        out = "rd1"
        for name, first in (("rd2", self.rd2_first_iteration), ("rd3", self.rd3_first_iteration), ("rd4", self.rd4_first_iteration)):
            if first is not None and int(iteration) >= first:
                out = name
        return out

    # -- construction from an rd2-readable archive -----------------------------------------------------------------------------------------

    @classmethod
    def adopt(cls, a: s2.Archive2) -> "Archive4":                    # type: ignore[override]
        """The same archive state as `a` (rd2's loader did the work), as an Archive4. Requires rd2's and rd3's session events, and rd4's if present."""
        out = cls.__new__(cls)
        out.__dict__.update(a.__dict__)
        out.draw_id_rd2 = str(out.archive_id) + DRAW_SUFFIX_RD2
        out.draw_id_rd3 = str(out.archive_id) + DRAW_SUFFIX_RD3
        out.draw_id_rd4 = str(out.archive_id) + DRAW_SUFFIX
        out._v3 = False
        sess = [e for e in out.events if e["ev"] == "session"]
        names = [e.get("name") for e in sess]
        if names not in ([SESSION_NAME_RD2, SESSION_NAME_RD3], [SESSION_NAME_RD2, SESSION_NAME_RD3, SESSION_NAME]):
            raise Select4Error(f"session events {names}: an rd4 archive carries rd2's and rd3's and at most rd4's")
        out.rd2_first_iteration = int(sess[0]["first_iteration"])
        out.rd3_first_iteration = int(sess[1]["first_iteration"])
        if len(sess) == 3:
            out.rd4_first_iteration = int(sess[2]["first_iteration"])
            out.draw_id = out.draw_id_rd4
        else:
            out.rd4_first_iteration = None
            out.draw_id = out.draw_id_rd3
        return out

    @staticmethod
    def read_dir(directory: Path, *, clf: Optional[mcell.Classifier] = None, floor_min: Optional[float] = None) -> Tuple["Archive4", Dict[str, Any]]:   # type: ignore[override]
        """Load an archive directory (rd3's closing archive or an rd4 checkpoint) after verifying its manifest; the derived state is rebuilt."""
        a, meta = s2.Archive2.read_dir(directory, clf=clf, floor_min=floor_min)
        return Archive4.adopt(a), meta

    # -- persistence -----------------------------------------------------------------------------------------------------------------------

    def write_files(self, directory: Path, meta: Mapping[str, Any]) -> Dict[str, str]:
        extra = dict(meta, archive4_contract=ARCHIVE4_CONTRACT, rd4_first_iteration=self.rd4_first_iteration,
                     draw_ids4={"rd1": self.archive_id, "rd2": self.draw_id_rd2, "rd3": self.draw_id_rd3, "rd4": self.draw_id_rd4 if self.rd4_first_iteration is not None else None},
                     select3_contract=SELECT3_CONTRACT if self.rd4_first_iteration is not None else None,
                     select3_digest=next((e["digest"] for e in self.events if e["ev"] == "session" and e.get("name") == SESSION_NAME), None))
        # rd2's writer stores `select2_digest` = the LAST session event's digest; in an rd4 checkpoint that is v3's. `select3_digest` and `select3_contract` name it unambiguously.
        return super().write_files(directory, extra)


# -- the ledger rebuild and audit (four parts) -----------------------------------------------------------------------------------------------


def dispatch_row(a: Archive4, c: march.Cell, iteration: int) -> Dict[str, Any]:
    """The start cell's state AT DISPATCH (call it after the selection and before `apply_dispatch`): what the mechanism check and the readings need."""
    return {"it": int(iteration), "cell": c.id, "seen": c.seen, "chosen": c.chosen, "L": c.L, "level": c.level, "res": c.key[2], "floor": c.key[4], "key": list(c.key),
            "x": float(c.end[mcell.I_X]), "y": float(c.end[mcell.I_Y]), "created_it": c.first_iter, "created_in": a.session_of_iteration(c.first_iter) if c.id else "rd1",
            "terminal": c.terminal}


def rebuild4(saved: s2.Archive2, lines_sha256: str, on_dispatch: Optional[Callable[[Dict[str, Any]], None]] = None) -> Archive4:
    """Replay the ordered ledger over the stored bursts: rd1's part under v1, rd2's `session` event and part under v2 (draw id `_v2`), rd3's under v2 (`_rd3`), rd4's `session` event and
    part under v3 (`_rd4`). Every selection is re-derived and every insert / replace / keep decision is re-checked. Zero native ticks. `on_dispatch(row)` is called for every dispatch
    with the start cell's counters at dispatch (before `apply_dispatch` increments them)."""
    if not saved.cells:
        raise march.ArchiveError("nothing to rebuild")
    out = Archive4(saved.archive_id, clf=saved.clf, floor_min=saved.floor_min)
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
            elif name == SESSION_NAME:
                made = out.begin_rd4(int(ev["first_iteration"]), lines_sha256)
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


def audit4(saved: s2.Archive2, lines_sha256: str, *, collect_rows_from: Optional[int] = None) -> Dict[str, Any]:
    """The close audit of the four-part archive: the ledger rebuilds it exactly; every prefix reconstructs; the incremental derived state equals the first-principles recomputation; the
    dispatch iterations are strictly increasing and never reused; every session event precedes the dispatches of its part. With `collect_rows_from` the audit's own rebuild also returns
    the dispatch rows (`dispatch_rows`) of every iteration from that one on (rd4's mechanism readings), so the ledger is rebuilt once."""
    problems: List[str] = []
    rows: List[Dict[str, Any]] = []

    def hook(row: Dict[str, Any]) -> None:
        if collect_rows_from is not None and row["it"] >= collect_rows_from:
            rows.append(row)

    try:
        rebuilt = rebuild4(saved, lines_sha256, on_dispatch=hook if collect_rows_from is not None else None)
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
    except (march.ArchiveError, Select4Error, s3.Select3Error, s2.Select2Error, KeyError, IndexError, ValueError, TypeError) as exc:
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
    return {"ok": not problems, "problems": problems[:20], "cells": len(saved.cells), "bursts": len(saved.bursts), "events": len(saved.events), "prefixes_reconstructed": lengths_ok,
            "dispatch_rows": rows}
