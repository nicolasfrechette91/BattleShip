"""Fast-route lab (frs): the lab archive on sd2's archive class (pure, standard library only).

`LabArchive` extends `m8_sd2_select.Archive6` (unchanged; reused by import and subclass only) with:

    E6 switch       `_end_bound` returns False when E6 is off, so no cell is bound-excluded and no new reach is bound-doomed (decision Q5,
                    review S7: this changes which inherited cells are eligible, not only the weights)
    lab session     one ledger `session` event named `frs_lab` (mode lab): its draw id, its first iteration and its E7 bound from the
                    reference passed in (the imported best verified clear), fixed for the run; the registered `adopt` refuses an archive
                    carrying it, so a lab archive can never pass for a registered one
    quarantine      a cell whose stored prefix no longer reproduces is made ineligible for the rest of the run (review S11)
    continuation    F3's trigger at a segment boundary: a reach of the last k words whose key is new to the archive or strictly shorter
                    than the incumbent (doom is not known there; it is assigned at ingest, where the whole continued job is ONE burst)
    provenance      every lab burst's words re-derive exactly from its keyed explorer stream

Selection is sd2's `m8_rd_select_v4` unchanged (harmonic level draw, v4 weights, E1-E5, X1, E7). Nothing here reads a position, a surface, a
target identity or a route tick. Design: logs/frs_prep/phase1_plan.md sections 3 and 4.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_sd2_select as s6  # noqa: E402

LAB_SESSION = "frs_lab"
LAB_ARCHIVE_CONTRACT = "frs_lab_archive_v1"
REGISTERED_SESSIONS = (s6.SESSION_NAME_RD2, s6.SESSION_NAME_RD3, s6.SESSION_NAME_RD4, s6.SESSION_NAME_SD1, s6.SESSION_NAME)
QUARANTINE_KINDS = ("prefix_end", "prefix_ended", "terminal_expected")
LABEL_RE = re.compile(r"^[a-z0-9]{1,24}$")


class LabArchiveError(RuntimeError):
    """A violated lab-archive invariant."""


def draw_id_for(archive_id: str, label: str) -> str:
    """The lab draw id (selection and explore keys) of a replicate label: both arms of a label pair share it (common random numbers)."""
    if not LABEL_RE.match(str(label)):
        raise LabArchiveError(f"a replicate label is 1-24 lower-case letters or digits, got {label!r}")
    return f"{archive_id}_frs_{label}"


def norm_key(k: Sequence[Any]) -> march.Key:
    return (int(k[0]), int(k[1]), str(k[2]), int(k[3]), int(k[4]))


def record_reference_from_route(meta: Mapping[str, Any], source: str) -> Dict[str, Any]:
    """The E7 reference block (sd1's validated format) from a verified route's metadata: its own clocks, digest, words and identity."""
    clocks = meta["completion_clocks"]
    return s6.record_reference_block(completion_input_tick=int(clocks["completion_input_tick"]),
                                     completion_time_passed=int(clocks["completion_time_passed"]),
                                     native_action_digest=str(meta["native_action_digest"]), words=int(meta["words"]),
                                     cid=int(meta["candidate"]["cid"]), iteration=int(meta["iteration"]), kind=str(meta["candidate"]["kind"]),
                                     session=str(meta["session"]), source=str(source))


def lab_contract_digest(description: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(description, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def stream_words(draw_id: str, iteration: int, n: int) -> bytes:
    """The first n words of an iteration's keyed explorer stream (m8_rd_explore_v1 holds are clipped only at the stream's end, so the first
    n words of any longer stream are these)."""
    return bytes(mx.words(lambda i: mx.explore_key(draw_id, int(iteration), i), int(n)))


class LabArchive(s6.Archive6):
    """Built only by `from_archive6` (or `read_lab_dir`); takes ownership of the Archive6 it is built from."""

    e6: bool = True

    # -- construction ----------------------------------------------------------------------------------------------------------------------

    @classmethod
    def from_archive6(cls, a6: s6.Archive6, *, e6: bool) -> "LabArchive":
        names = [e.get("name") for e in a6.events if e["ev"] == "session"]
        if tuple(names) != REGISTERED_SESSIONS:
            raise LabArchiveError(f"the lab starts from an archive with exactly sd2's session history {REGISTERED_SESSIONS}, got {names}")
        if a6._pending:
            raise LabArchiveError(f"{len(a6._pending)} dispatched iterations are still pending in the imported archive")
        out = cls.__new__(cls)
        out.__dict__.update(a6.__dict__)
        out.events = list(a6.events)
        out.bound = list(a6.bound)
        out._elig5 = None
        out._elig6 = None
        out.e6 = True
        out.lab_first_iteration = None
        out.draw_id_lab = None
        out.lab_bound_L = None
        out.lab_reference = None
        out.lab_margin = None
        out.lab_event = None
        out.quarantined = set()
        out.import_counts = {"cells": len(out.cells), "bursts": len(out.bursts), "events": len(out.events)}
        out.set_e6(e6)
        return out

    @staticmethod
    def read_import(directory: Path, *, e6: bool) -> Tuple["LabArchive", Dict[str, Any], s6.Archive6]:
        """Load sd2's closing archive (manifest verified by the registered loader) and adopt it. The Archive6 is returned for the equality
        check only; it must not be used once the lab archive is mutated."""
        a2, meta = s2.Archive2.read_dir(Path(directory))
        a6 = s6.Archive6.adopt(a2)
        return LabArchive.from_archive6(a6, e6=e6), meta, a6

    @staticmethod
    def read_lab_dir(directory: Path) -> Tuple["LabArchive", Dict[str, Any]]:
        """Load a closing lab archive (analysis and tests): the lab session event is set aside for the registered adopt, then restored."""
        a2, meta = s2.Archive2.read_dir(Path(directory))
        events = list(a2.events)
        lab_ev = [e for e in events if e["ev"] == "session" and e.get("name") == LAB_SESSION]
        if len(lab_ev) != 1:
            raise LabArchiveError(f"a lab archive carries exactly one {LAB_SESSION} event, found {len(lab_ev)}")
        a2.events = [e for e in events if not (e["ev"] == "session" and e.get("name") == LAB_SESSION)]
        a6 = s6.Archive6.adopt(a2)
        a6._pending = {}
        out = LabArchive.from_archive6(a6, e6=bool(lab_ev[0]["e6"]))
        out.events = events
        ev = lab_ev[0]
        out.configure_lab(first_iteration=int(ev["first_iteration"]), draw_id=str(ev["draw_id"]), record_reference=ev["record_reference"],
                          margin=int(ev["margin"]), check_iterations=False)
        out.lab_event = ev
        fl = meta.get("frs_lab") or {}
        if fl.get("import_counts"):
            out.import_counts = dict(fl["import_counts"])
        out.quarantined = set(int(c) for c in fl.get("quarantined", []))
        return out, meta

    # -- E6 -----------------------------------------------------------------------------------------------------------------------------------

    def _end_bound(self, res: str, end: Sequence[Any]) -> bool:
        if not getattr(self, "e6", True):
            return False
        return super()._end_bound(res, end)

    def set_e6(self, on: bool) -> None:
        self.e6 = bool(on)
        self.bound = [self._end_bound(c.key[2], c.end) for c in self.cells]
        self._version += 1

    # -- the lab session ---------------------------------------------------------------------------------------------------------------------

    def configure_lab(self, *, first_iteration: int, draw_id: str, record_reference: Mapping[str, Any], margin: int,
                      check_iterations: bool = True) -> None:
        s6.validate_record_reference(record_reference)
        if not isinstance(margin, int) or isinstance(margin, bool) or margin < 1:
            raise LabArchiveError(f"the margin is a positive integer number of ticks, got {margin!r}")
        prior = [e["it"] for e in self.events if e["ev"] == "dispatch"]
        if check_iterations and prior and int(first_iteration) <= max(prior):
            raise LabArchiveError(f"first iteration {first_iteration} would reuse iteration {max(prior)}")
        self.lab_first_iteration = int(first_iteration)
        self.draw_id_lab = str(draw_id)
        self.lab_reference = dict(record_reference)
        self.lab_margin = int(margin)
        self.lab_bound_L = s6.record_bound_max_L(int(record_reference["completion_input_tick"]), int(margin))
        self._version += 1

    def next_iteration(self) -> int:
        its = [e["it"] for e in self.events if e["ev"] == "dispatch"]
        return (max(its) + 1) if its else 0

    def begin_lab(self, *, run_id: str, draw_id: str, record_reference: Mapping[str, Any], margin: int, explore: Mapping[str, Any]
                  ) -> Dict[str, Any]:
        if self.lab_event is not None:
            raise LabArchiveError("the lab session has already begun")
        if self._pending:
            raise LabArchiveError(f"{len(self._pending)} dispatched iterations are still pending")
        first = self.next_iteration()
        self.configure_lab(first_iteration=first, draw_id=draw_id, record_reference=record_reference, margin=margin)
        desc = {"contract": LAB_ARCHIVE_CONTRACT, "select": s6.SELECT4_CONTRACT, "e6": self.e6, "draw_id": self.draw_id_lab,
                "record_reference": self.lab_reference, "margin": self.lab_margin, "bound_max_L": self.lab_bound_L, "explore": dict(explore)}
        ev = {"ev": "session", "name": LAB_SESSION, "mode": "lab", "run": str(run_id), "select": s6.SELECT4_CONTRACT,
              "digest": lab_contract_digest(desc), "first_iteration": first, "draw_id": self.draw_id_lab, "record_reference": self.lab_reference,
              "margin": self.lab_margin, "bound_max_L": self.lab_bound_L, "e6": self.e6, "explore": dict(explore)}
        self.events.append(ev)
        self.lab_event = ev
        return ev

    def _lab(self, iteration: int) -> bool:
        return self.lab_first_iteration is not None and int(iteration) >= self.lab_first_iteration

    def draw_for(self, iteration: int) -> str:
        if self._lab(iteration):
            return str(self.draw_id_lab)
        return super().draw_for(iteration)

    def bound_for(self, iteration: int) -> Optional[int]:
        if self._lab(iteration):
            return self.lab_bound_L
        return super().bound_for(iteration)

    def session_of_iteration(self, iteration: int) -> str:
        if self._lab(iteration):
            return LAB_SESSION
        return super().session_of_iteration(iteration)

    # -- quarantine ----------------------------------------------------------------------------------------------------------------------------

    def eligible(self, c: march.Cell) -> bool:                       # type: ignore[override]
        if c.id in self.quarantined:
            return False
        return super().eligible(c)

    def quarantine(self, cell_id: int, iteration: int, why: str) -> None:
        if int(cell_id) == 0:
            raise LabArchiveError("cell 0 (the tick-0 reset) cannot be quarantined")
        self.quarantined.add(int(cell_id))
        self.note_failure(int(iteration), f"quarantine: {why}")
        self._version += 1

    # -- readings --------------------------------------------------------------------------------------------------------------------------------

    def lab_probabilities(self) -> Dict[int, float]:
        if self.lab_bound_L is None:
            raise LabArchiveError("the lab bound is not set")
        return self.probabilities_at_bound(self.lab_bound_L)

    def continuation_decision(self, reaches: Iterable[Sequence[Any]]) -> Dict[str, Any]:
        """F3's trigger on the current archive: any reported reach (j, key) whose key is new, or whose j is strictly below the incumbent's L."""
        new = shorter = n = 0
        gain = 0
        for j, k in reaches:
            n += 1
            cid = self.by_key.get(norm_key(k))
            if cid is None:
                new += 1
                continue
            g = self.cells[cid].L - int(j)
            if g > 0:
                shorter += 1
                gain = max(gain, g)
        return {"reaches": n, "new": new, "shorter": shorter, "max_gain": gain, "go": (new + shorter) > 0, "cells": len(self.cells)}

    def fastest_arrival(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for c in self.cells:
            k = str(c.level)
            if k not in out or c.L < out[k]:
                out[k] = c.L
        return dict(sorted(out.items(), key=lambda kv: int(kv[0])))

    def lab_bursts(self) -> List[march.Burst]:
        return self.bursts[int(self.import_counts["bursts"]):]

    def provenance(self, burst: march.Burst) -> bool:
        if not self._lab(burst.iteration):
            return False
        return stream_words(self.draw_for(burst.iteration), burst.iteration, len(burst.words)) == bytes(burst.words)

    def lineage(self, burst_id: int) -> List[int]:
        """Burst ids from tick 0 to `burst_id` (the representative chain each burst pinned at dispatch)."""
        out: List[int] = []
        b = int(burst_id)
        while b != -1:
            out.append(b)
            b = self.bursts[b].start_rep[0]
        return list(reversed(out))

    def lineage_provenance(self, burst_id: int) -> Dict[str, Any]:
        """Word provenance of a trajectory: its lab bursts re-derive from their keys; its inherited bursts belong to the hashed import."""
        chain = self.lineage(burst_id)
        lab = [b for b in chain if b >= int(self.import_counts["bursts"])]
        bad = [b for b in lab if not self.provenance(self.bursts[b])]
        return {"bursts": len(chain), "lab_bursts": len(lab), "inherited_bursts": len(chain) - len(lab), "bad": bad, "ok": not bad}

    def write_lab(self, directory: Path, meta: Mapping[str, Any]) -> Dict[str, str]:
        extra = dict(meta, frs_mode="lab", frs_lab_contract=LAB_ARCHIVE_CONTRACT,          # `mode` is the registered archive mode (2)
                     frs_lab={"import_counts": dict(self.import_counts), "quarantined": sorted(self.quarantined), "e6": self.e6,
                              "lab_first_iteration": self.lab_first_iteration, "draw_id": self.draw_id_lab, "bound_max_L": self.lab_bound_L})
        return self.write_files(Path(directory), extra)


# -- the E6-on equality check and the E6-off census (self-check, review S7) -------------------------------------------------------------------


def e6_census(lab: LabArchive, a6: s6.Archive6, *, draws: int = 200) -> Dict[str, Any]:
    """With E6 ON, the lab archive must select exactly as sd2's Archive6 at the same bound and draw id (probabilities and keyed draws); then
    E6 is switched OFF and the cells it makes eligible are counted per level with their v4 mass. Leaves the lab archive with E6 off."""
    if not lab.e6 or lab.lab_bound_L is None or lab.lab_first_iteration is None:
        raise LabArchiveError("the census needs a configured lab archive with E6 on")
    b = lab.lab_bound_L
    p_on = lab.lab_probabilities()
    p6 = a6.probabilities_at_bound(b)
    keep = (a6.draw_id_sd2, a6._bound_L)
    a6.draw_id_sd2, a6._bound_L = lab.draw_id_lab, b
    try:
        its = range(lab.lab_first_iteration, lab.lab_first_iteration + int(draws))
        same_draws = sum(1 for it in its if lab.select(it).id == a6.select(it).id)
    finally:
        a6.draw_id_sd2, a6._bound_L = keep
    bound_on = sum(1 for x in lab.bound if x)
    lab.set_e6(False)
    p_off = lab.lab_probabilities()
    per: Dict[str, Dict[str, Any]] = {}
    for c in lab.cells:
        on, off = c.id in p_on, c.id in p_off
        if not (on or off):
            continue
        d = per.setdefault(str(c.level), {"eligible_e6_on": 0, "eligible_e6_off": 0, "made_eligible": 0, "mass_on": 0.0, "mass_off": 0.0,
                                          "mass_made_eligible": 0.0})
        d["eligible_e6_on"] += int(on)
        d["eligible_e6_off"] += int(off)
        d["mass_on"] += p_on.get(c.id, 0.0)
        d["mass_off"] += p_off.get(c.id, 0.0)
        if off and not on:
            d["made_eligible"] += 1
            d["mass_made_eligible"] += p_off[c.id]
    for d in per.values():
        for k in ("mass_on", "mass_off", "mass_made_eligible"):
            d[k] = round(d[k], 6)
    return {"equal_probabilities": p_on == p6, "eligible_on": len(p_on), "draws": int(draws), "same_draws": same_draws,
            "bound_flags_e6_on": bound_on, "eligible_off": len(p_off), "made_eligible": len(set(p_off) - set(p_on)),
            "lost_eligibility": len(set(p_on) - set(p_off)),
            "per_level": dict(sorted(per.items(), key=lambda kv: int(kv[0])))}


def first_iterations(a: s6.Archive6) -> Dict[str, Optional[int]]:
    return {"rd2": a.rd2_first_iteration, "rd3": a.rd3_first_iteration, "rd4": a.rd4_first_iteration, "sd1": a.sd1_first_iteration,
            "sd2": a.sd2_first_iteration}
