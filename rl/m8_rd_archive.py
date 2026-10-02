"""M8-rd: the return archive (cells, bursts, selection `m8_rd_select_v1`, lineage, atomic checkpoints, ledger audit).

Pure (standard library only, no game). Design: docs/rl_m8_rd_proposal_2026-10-01.md (revision 2) sections 4, 5 and 8.

Every cell is one EXACT own trajectory from tick 0: the first live reach of its key along a burst that started from another
cell's representative. A cell's words are reconstructed by walking (burst, offset) -> the burst's pinned start representative
-> ... -> the empty root (cell 0 = the tick-0 reset). The start representative a burst replayed is PINNED in the burst
(`start_rep`), because the start cell's own representative may be replaced later by a shorter or non-doomed reach: the burst's
trajectory stays exact through the representative it actually replayed.

The archive state is a deterministic function of the ordered event ledger (`dispatch` and `ingest` events) and the stored
bursts. `rebuild` replays the ledger, re-derives every selection and every insert / replace / keep decision, and the audit
compares the rebuilt cells with the saved ones.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import m8_rd_cells as mcell
import m8_rd_explore as mx

ARCHIVE_SCHEMA = "m8_rd_archive_v1"
SELECT_CONTRACT = "m8_rd_select_v1"
DOOM_WINDOW = 60                       # ticks before a native fall within which a reach is doomed (M7h's window)
VELOCITY_REVERSAL_MIN = 6.0            # |vx| of both representatives for the reported velocity-reversal reading
LENGTH_SCALE = 900.0                   # w_len = 900 / (900 + L - L_min(level))
MAX_ELIGIBLE_L = mcell.HORIZON - mx.BURST_WORDS     # one full burst must fit inside the horizon
ACTION_NEW, ACTION_REPLACE, ACTION_KEEP = 0, 1, 2
DATA_FILES = ("archive_meta.json", "cells.jsonl", "bursts.bin", "bursts.idx.jsonl", "events.jsonl")
MANIFEST = "manifest.sha256"
EXECUTABLE_RUNTIME_DIR = "runtime"

Key = Tuple[int, int, str, int, int]


class ArchiveError(RuntimeError):
    """A violated archive invariant (never silently tolerated)."""


def select_contract_digest() -> str:
    d = {"contract": SELECT_CONTRACT, "eligibility": ["not doomed", "resource class != X", "representative did not end the "
                                                      "episode at L", f"L <= {MAX_ELIGIBLE_L}", "cell 0 always eligible"],
         "level": "10 - popcount(mask); weight 2^-(top - level) over the levels that have eligible cells",
         "cell_weight": "(1/sqrt(1+chosen) + 1/sqrt(1+seen)) * 900 / (900 + L - L_min(level))",
         "doom_window": DOOM_WINDOW, "length_scale": LENGTH_SCALE,
         "replacement": "a non-doomed reach beats a doomed one; then the strictly shorter L; ties keep the incumbent",
         "draws": "two uniforms from sha256(m8_rd|<archive_id>|select|<iteration>), cells in id order"}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- cells and bursts ----------------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Cell:
    id: int
    key: Key
    level: int
    L: int
    burst: int                    # representative: burst id (-1 for cell 0)
    offset: int                   # words of that burst the representative uses (L = start_L of that burst + offset)
    parent: int                   # start cell of that burst (informational; -1 for cell 0)
    end: Tuple[Any, ...]          # the 17 observation values at the reach (host_frame included)
    end_digest: bytes             # sha256 of the canonical per-tick record at the reach
    chain: bytes                  # chain digest h_L
    doomed: bool
    terminal: bool                # the reach is the native end of the episode (a clear, an end, a fall)
    chosen: int = 0
    seen: int = 0
    produced: int = 0
    first_iter: int = -1
    last_iter: int = -1
    replacements: int = 0
    first_cum: int = 0

    def to_json(self) -> Dict[str, Any]:
        return {"id": self.id, "key": list(self.key), "level": self.level, "L": self.L, "burst": self.burst,
                "offset": self.offset, "parent": self.parent, "end": list(self.end), "ed": self.end_digest.hex(),
                "ch": self.chain.hex(), "doomed": int(self.doomed), "terminal": int(self.terminal), "chosen": self.chosen,
                "seen": self.seen, "produced": self.produced, "first_iter": self.first_iter, "last_iter": self.last_iter,
                "repl": self.replacements, "first_cum": self.first_cum}

    @staticmethod
    def from_json(d: Mapping[str, Any]) -> "Cell":
        k = d["key"]
        return Cell(id=int(d["id"]), key=(int(k[0]), int(k[1]), str(k[2]), int(k[3]), int(k[4])), level=int(d["level"]),
                    L=int(d["L"]), burst=int(d["burst"]), offset=int(d["offset"]), parent=int(d["parent"]),
                    end=tuple(d["end"]), end_digest=bytes.fromhex(d["ed"]), chain=bytes.fromhex(d["ch"]),
                    doomed=bool(d["doomed"]), terminal=bool(d["terminal"]), chosen=int(d["chosen"]), seen=int(d["seen"]),
                    produced=int(d["produced"]), first_iter=int(d["first_iter"]), last_iter=int(d["last_iter"]),
                    replacements=int(d["repl"]), first_cum=int(d["first_cum"]))


@dataclass(slots=True)
class Burst:
    id: int
    start_cell: int
    start_rep: Tuple[int, int]    # (burst, offset) of the start cell's representative AT DISPATCH (-1, 0 for cell 0)
    start_L: int
    words: bytes                  # Track 1 word indices, one per native tick of the burst
    end_reason: str
    iteration: int
    session: str
    worker: int
    ticks: int                    # native ticks of the whole job (prefix replay + burst)
    fall_tick: Optional[int]      # absolute tick of the native failure, when the burst ended in one
    cum_before: int
    reaches: List[List[int]] = field(default_factory=list)       # [j, cell id, action] per distinct visited key, in order
    wins: List[Dict[str, Any]] = field(default_factory=list)     # data of the reaches whose action was NEW or REPLACE

    def to_json(self, bin_offset: int) -> Dict[str, Any]:
        return {"id": self.id, "start_cell": self.start_cell, "start_rep": list(self.start_rep), "start_L": self.start_L,
                "bin_off": bin_offset, "n": len(self.words), "end_reason": self.end_reason, "iteration": self.iteration,
                "session": self.session, "worker": self.worker, "ticks": self.ticks, "fall_tick": self.fall_tick,
                "cum_before": self.cum_before, "reaches": self.reaches, "wins": self.wins}


def _better(old_doomed: bool, old_L: int, new_doomed: bool, new_L: int) -> bool:
    """Replacement rule (section 4.3): a non-doomed reach beats a doomed one; then the strictly shorter L; ties keep the
    incumbent."""
    if old_doomed != new_doomed:
        return not new_doomed
    return new_L < old_L


# -- the archive ---------------------------------------------------------------------------------------------------------------


class Archive:
    def __init__(self, archive_id: str):
        self.archive_id = str(archive_id)
        self.cells: List[Cell] = []
        self.by_key: Dict[Key, int] = {}
        self.bursts: List[Burst] = []
        self.events: List[Dict[str, Any]] = []
        self._level_cells: Dict[int, List[Cell]] = {}
        self._version = 0
        self._elig: Optional[Tuple[int, Dict[int, List[Cell]]]] = None
        # iteration -> (cell id, representative (burst, offset), L) AT DISPATCH: ingestion is asynchronous, so a cell may be
        # replaced while a job that started from its older representative is still running; the job's result must match
        # what was dispatched, not the cell's current representative
        self._pending: Dict[int, Tuple[int, Tuple[int, int], int]] = {}
        # reported, never deciding (section 11.3): airborne replacements whose horizontal velocity changed sign
        self.diag: Dict[str, Any] = {"velocity_reversals": 0, "velocity_reversal_examples": []}

    # -- construction ------------------------------------------------------------------------------------------------------

    def init_cell0(self, key: Key, end: Sequence[Any], end_digest: bytes, chain: bytes) -> Cell:
        if self.cells:
            raise ArchiveError("cell 0 already exists")
        c = Cell(id=0, key=tuple(key), level=mcell.level_of_mask(key[3]), L=0, burst=-1, offset=0, parent=-1, end=tuple(end),
                 end_digest=bytes(end_digest), chain=bytes(chain), doomed=False, terminal=False, first_iter=-1, last_iter=-1)
        self._add(c)
        return c

    def _add(self, c: Cell) -> None:
        self.cells.append(c)
        self.by_key[c.key] = c.id
        self._level_cells.setdefault(c.level, []).append(c)
        self._version += 1

    # -- eligibility and selection -------------------------------------------------------------------------------------------

    @staticmethod
    def eligible(c: Cell) -> bool:
        if c.id == 0:
            return True
        return (not c.doomed) and c.key[2] != mcell.RES_X and (not c.terminal) and c.L <= MAX_ELIGIBLE_L

    def eligible_levels(self) -> Dict[int, List[Cell]]:
        if self._elig is not None and self._elig[0] == self._version:
            return self._elig[1]
        out: Dict[int, List[Cell]] = {}
        for lv, cs in self._level_cells.items():
            e = [c for c in cs if self.eligible(c)]
            if e:
                out[lv] = e
        self._elig = (self._version, out)
        return out

    def select(self, iteration: int) -> Cell:
        """m8_rd_select_v1: level by 2^-(top - level) over the levels with eligible cells, then a cell by novelty times the
        prefix-length factor. Two keyed uniforms; no generator state."""
        levels = self.eligible_levels()
        if not levels:
            raise ArchiveError("no eligible cell")
        top = max(levels)
        u1, u2 = mx.uniforms(mx.select_key(self.archive_id, iteration))
        order = sorted(levels)
        wl = [2.0 ** -(top - lv) for lv in order]
        r = u1 * sum(wl)
        acc = 0.0
        level = order[-1]
        for lv, w in zip(order, wl):
            acc += w
            if r < acc:
                level = lv
                break
        cells = levels[level]
        lmin = min(c.L for c in cells)
        ws = [(1.0 / math.sqrt(1 + c.chosen) + 1.0 / math.sqrt(1 + c.seen)) * (LENGTH_SCALE / (LENGTH_SCALE + c.L - lmin))
              for c in cells]
        r = u2 * sum(ws)
        acc = 0.0
        for c, w in zip(cells, ws):
            acc += w
            if r < acc:
                return c
        return cells[-1]

    def dispatch(self, iteration: int, worker: int) -> Cell:
        c = self.select(iteration)
        self.apply_dispatch(iteration, c.id, worker)
        return c

    def apply_dispatch(self, iteration: int, cell_id: int, worker: int) -> None:
        c = self.cells[cell_id]
        c.chosen += 1
        self._version += 1
        self._pending[int(iteration)] = (int(cell_id), (c.burst, c.offset), c.L)
        self.events.append({"ev": "dispatch", "it": int(iteration), "cell": int(cell_id), "worker": int(worker), "L": c.L,
                            "rep": [c.burst, c.offset]})

    def note_failure(self, iteration: int, why: str) -> None:
        self._pending.pop(int(iteration), None)
        self.events.append({"ev": "fail", "it": int(iteration), "why": str(why)[:200]})

    # -- lineage ---------------------------------------------------------------------------------------------------------------

    def rep_words(self, burst_id: int, offset: int) -> bytes:
        segs: List[bytes] = []
        b, o = int(burst_id), int(offset)
        for _ in range(len(self.bursts) + 2):
            if b == -1:
                return b"".join(reversed(segs))
            if not 0 <= b < len(self.bursts):
                raise ArchiveError(f"lineage reaches unknown burst {b}")
            burst = self.bursts[b]
            if not 0 <= o <= len(burst.words):
                raise ArchiveError(f"burst {b}: offset {o} outside 0..{len(burst.words)}")
            segs.append(burst.words[:o])
            nb, no = burst.start_rep
            if nb >= b:
                raise ArchiveError(f"burst {b} starts from a later burst {nb}")
            b, o = nb, no
        raise ArchiveError("lineage cycle")

    def cell_words(self, c: Cell) -> bytes:
        w = self.rep_words(c.burst, c.offset)
        if len(w) != c.L:
            raise ArchiveError(f"cell {c.id}: prefix has {len(w)} words, L = {c.L}")
        return w

    # -- ingestion -------------------------------------------------------------------------------------------------------------

    def decide(self, key: Key, new_L: int, new_doomed: bool) -> Tuple[int, Optional[Cell]]:
        cid = self.by_key.get(key)
        if cid is None:
            return ACTION_NEW, None
        c = self.cells[cid]
        if _better(c.doomed, c.L, new_doomed, new_L):
            return ACTION_REPLACE, c
        return ACTION_KEEP, c

    def ingest(self, res: Mapping[str, Any]) -> Dict[str, Any]:
        """Insert one finished job (section 5.4). `res` keys: iteration, cell (start cell id), rep (burst, offset), L (prefix
        words replayed), words (burst bytes), end_reason, ticks, reaches [(j, key, end tuple, end digest, chain, terminal)],
        worker, session, cum_before. Prefix rows are never inserted; only distinct first reaches along the burst are."""
        it = int(res["iteration"])
        start = self.cells[int(res["cell"])]
        words = bytes(res["words"])
        start_L = int(res["L"])
        pend = self._pending.pop(it, None)
        replayed = (int(res["rep"][0]), int(res["rep"][1]))
        if pend is not None:
            if pend != (start.id, replayed, start_L):
                raise ArchiveError(f"iteration {it}: the result is for (cell {start.id}, rep {replayed}, L {start_L}) but "
                                   f"{pend} was dispatched")
        elif len(self.rep_words(*replayed)) != start_L:
            raise ArchiveError(f"iteration {it}: the replayed representative {replayed} has no {start_L}-word trajectory")
        if not words:
            self.events.append({"ev": "ingest", "it": it, "burst": -1, "cum": int(res["cum_before"]), "ticks": int(res["ticks"])})
            return {"burst": -1, "new": 0, "replaced": 0, "kept": 0, "visited": 0, "new_ids": []}
        fall_tick = start_L + len(words) if res["end_reason"] == "fall" else None
        burst = Burst(id=len(self.bursts), start_cell=start.id, start_rep=replayed, start_L=start_L,
                      words=words, end_reason=str(res["end_reason"]), iteration=it, session=str(res.get("session", "")),
                      worker=int(res.get("worker", -1)), ticks=int(res["ticks"]), fall_tick=fall_tick,
                      cum_before=int(res["cum_before"]))
        visited: List[int] = []
        seen_ids = set()
        new_ids: List[int] = []
        replaced = kept = 0
        last_j = start_L
        for j, key, end, ed, ch, terminal in res["reaches"]:
            j = int(j)
            if not start_L < j <= start_L + len(words) or j <= last_j:
                raise ArchiveError(f"iteration {it}: reach tick {j} outside the burst or out of order")
            last_j = j
            key = (int(key[0]), int(key[1]), str(key[2]), int(key[3]), int(key[4]))
            doomed = fall_tick is not None and fall_tick - j <= DOOM_WINDOW
            action, c = self.decide(key, j, doomed)
            data = dict(j=j, key=list(key), end=list(end), ed=bytes(ed).hex(), ch=bytes(ch).hex(), doomed=int(doomed),
                        terminal=int(bool(terminal)))
            if action == ACTION_NEW:
                c = Cell(id=len(self.cells), key=key, level=mcell.level_of_mask(key[3]), L=j, burst=burst.id,
                         offset=j - start_L, parent=start.id, end=tuple(end), end_digest=bytes(ed), chain=bytes(ch),
                         doomed=doomed, terminal=bool(terminal), first_iter=it, last_iter=it,
                         first_cum=burst.cum_before + j)
                self._add(c)
                new_ids.append(c.id)
                burst.wins.append(dict(data, cell=c.id, a=ACTION_NEW))
            elif action == ACTION_REPLACE:
                assert c is not None
                self._replace(c, j, burst, start, key, end, ed, ch, doomed, terminal, it)
                replaced += 1
                burst.wins.append(dict(data, cell=c.id, a=ACTION_REPLACE))
            else:
                assert c is not None
                kept += 1
            burst.reaches.append([j, c.id, action])
            if c.id not in seen_ids:
                seen_ids.add(c.id)
                visited.append(c.id)
        self.bursts.append(burst)
        for cid in visited:
            c = self.cells[cid]
            c.seen += 1
            c.last_iter = it
        start.produced += len(new_ids)
        self._version += 1
        self.events.append({"ev": "ingest", "it": it, "burst": burst.id, "cum": burst.cum_before, "ticks": burst.ticks})
        return {"burst": burst.id, "new": len(new_ids), "replaced": replaced, "kept": kept, "visited": len(visited),
                "new_ids": new_ids}

    def _replace(self, c: Cell, j: int, burst: Burst, start: Cell, key: Key, end: Sequence[Any], ed: bytes, ch: bytes,
                 doomed: bool, terminal: bool, it: int) -> None:
        old_vx, new_vx = c.end[mcell.I_VX], end[mcell.I_VX]
        if key[2] in (mcell.RES_A2, mcell.RES_A1, mcell.RES_A0) and abs(old_vx) >= VELOCITY_REVERSAL_MIN                 and abs(new_vx) >= VELOCITY_REVERSAL_MIN and old_vx * new_vx < 0:
            self.diag["velocity_reversals"] += 1
            if len(self.diag["velocity_reversal_examples"]) < 20:
                self.diag["velocity_reversal_examples"].append(
                    {"cell": c.id, "iteration": it, "old_L": c.L, "new_L": j, "old_vx": old_vx, "new_vx": new_vx})
        c.L = j
        c.burst = burst.id
        c.offset = j - burst.start_L
        c.parent = start.id
        c.end = tuple(end)
        c.end_digest = bytes(ed)
        c.chain = bytes(ch)
        c.doomed = doomed
        c.terminal = bool(terminal)
        c.replacements += 1
        c.last_iter = it

    # -- views -------------------------------------------------------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        by_level: Dict[int, Dict[str, int]] = {}
        for c in self.cells:
            d = by_level.setdefault(c.level, {"cells": 0, "eligible": 0, "doomed": 0})
            d["cells"] += 1
            d["eligible"] += int(self.eligible(c))
            d["doomed"] += int(c.doomed)
        top = max((lv for lv, d in by_level.items() if d["eligible"]), default=0)
        top_L = sorted(c.L for c in self.eligible_levels().get(top, []))
        return {"cells": len(self.cells), "bursts": len(self.bursts), "masks": len({c.key[3] for c in self.cells}),
                "bins": len({(c.key[0], c.key[1]) for c in self.cells}), "by_level": {str(k): by_level[k] for k in sorted(by_level)},
                "top_eligible_level": top, "top_level_median_L": (top_L[len(top_L) // 2] if top_L else None),
                "replacements": sum(c.replacements for c in self.cells), "doomed": sum(int(c.doomed) for c in self.cells),
                "resource": {r: sum(1 for c in self.cells if c.key[2] == r) for r in mcell.RESOURCE_CLASSES}}

    # -- persistence -------------------------------------------------------------------------------------------------------------

    def write_files(self, directory: Path, meta: Mapping[str, Any]) -> Dict[str, str]:
        """Write the five data files and the manifest into `directory` (created); every file is fsynced. Returns
        {name: sha256}."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        bin_off = 0
        bursts_lines: List[str] = []
        with open(directory / "bursts.bin", "wb") as fb:
            for b in self.bursts:
                fb.write(b.words)
                bursts_lines.append(json.dumps(b.to_json(bin_off), separators=(",", ":")))
                bin_off += len(b.words)
            fb.flush()
            os.fsync(fb.fileno())
        _write_lines(directory / "bursts.idx.jsonl", bursts_lines)
        _write_lines(directory / "cells.jsonl", (json.dumps(c.to_json(), separators=(",", ":")) for c in self.cells))
        _write_lines(directory / "events.jsonl", (json.dumps(e, separators=(",", ":")) for e in self.events))
        full = dict(meta, schema=ARCHIVE_SCHEMA, archive_id=self.archive_id, cells=len(self.cells), bursts=len(self.bursts),
                    events=len(self.events), select_contract=SELECT_CONTRACT, select_digest=select_contract_digest(),
                    diag=self.diag)
        _write_text(directory / "archive_meta.json", json.dumps(full, indent=1, sort_keys=True) + "\n")
        return write_manifest(directory)

    @staticmethod
    def read_files(directory: Path) -> Tuple["Archive", Dict[str, Any]]:
        """Load an archive directory after verifying its manifest."""
        directory = Path(directory)
        bad = verify_manifest(directory)
        if bad:
            raise ArchiveError(f"{directory}: manifest verification failed: {bad[:4]}")
        meta = json.loads((directory / "archive_meta.json").read_text(encoding="utf-8"))
        if meta.get("schema") != ARCHIVE_SCHEMA:
            raise ArchiveError(f"{directory}: schema {meta.get('schema')!r}")
        a = Archive(meta["archive_id"])
        if meta.get("diag"):
            a.diag = {"velocity_reversals": int(meta["diag"]["velocity_reversals"]),
                      "velocity_reversal_examples": list(meta["diag"]["velocity_reversal_examples"])}
        for line in (directory / "cells.jsonl").read_text(encoding="utf-8").splitlines():
            a._add(Cell.from_json(json.loads(line)))
        blob = (directory / "bursts.bin").read_bytes()
        for line in (directory / "bursts.idx.jsonl").read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            off, n = int(d["bin_off"]), int(d["n"])
            a.bursts.append(Burst(id=int(d["id"]), start_cell=int(d["start_cell"]), start_rep=(int(d["start_rep"][0]),
                                  int(d["start_rep"][1])), start_L=int(d["start_L"]), words=blob[off:off + n],
                                  end_reason=d["end_reason"], iteration=int(d["iteration"]), session=d["session"],
                                  worker=int(d["worker"]), ticks=int(d["ticks"]), fall_tick=d["fall_tick"],
                                  cum_before=int(d["cum_before"]), reaches=[list(r) for r in d["reaches"]],
                                  wins=list(d["wins"])))
        a.events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        return a, meta


def _write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def _write_lines(path: Path, lines: Iterable[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for ln in lines:
            f.write(ln)
            f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(directory: Path) -> Dict[str, str]:
    directory = Path(directory)
    sums = {n: sha256_file(directory / n) for n in DATA_FILES}
    _write_text(directory / MANIFEST, "".join(f"{h}  {n}\n" for n, h in sums.items()))
    return sums


def verify_manifest(directory: Path) -> List[str]:
    """Problems (empty when the manifest names exactly the data files and every hash matches), re-read from disk."""
    directory = Path(directory)
    mp = directory / MANIFEST
    if not mp.is_file():
        return ["no manifest"]
    listed: Dict[str, str] = {}
    for line in mp.read_text(encoding="utf-8").splitlines():
        h, _, n = line.partition("  ")
        listed[n] = h
    problems = []
    if set(listed) != set(DATA_FILES):
        problems.append(f"manifest lists {sorted(listed)}")
    for n in DATA_FILES:
        p = directory / n
        if not p.is_file():
            problems.append(f"{n} missing")
        elif n in listed and sha256_file(p) != listed[n]:
            problems.append(f"{n} differs from the manifest")
    return problems


# -- atomic checkpoints --------------------------------------------------------------------------------------------------------


class SimulatedCrash(RuntimeError):
    """Test-only: raised by save_checkpoint at a requested step."""


def save_checkpoint(root: Path, archive: Archive, meta: Mapping[str, Any], *, crash_at: Optional[str] = None) -> Dict[str, str]:
    """root = <run>/archive. Steps: write <run>/archive.tmp, verify its manifest by re-reading, move the current data files
    into <run>/archive.prev, move the new ones into <run>/archive. archive/runtime (the frozen runtime copy) is untouched.
    A crash at any step leaves at least one directory whose manifest verifies (`load_latest_verified`)."""
    root = Path(root)
    run = root.parent
    tmp, prev = run / "archive.tmp", run / "archive.prev"
    if tmp.exists():
        rmtree_retry(tmp)
    sums = archive.write_files(tmp, meta)
    _maybe_crash(crash_at, "tmp_written")
    problems = verify_manifest(tmp)
    if problems:
        raise ArchiveError(f"checkpoint verification failed: {problems}")
    _maybe_crash(crash_at, "tmp_verified")
    if prev.exists():
        rmtree_retry(prev)
    prev.mkdir(parents=True)
    root.mkdir(parents=True, exist_ok=True)
    for n in (*DATA_FILES, MANIFEST):
        if (root / n).exists():
            replace_retry(root / n, prev / n)
    _maybe_crash(crash_at, "current_moved")
    for n in (*DATA_FILES, MANIFEST):
        replace_retry(tmp / n, root / n)
    _maybe_crash(crash_at, "new_installed")
    rmtree_retry(tmp)
    return sums


def replace_retry(src: Any, dst: Any, timeout: float = 15.0) -> None:
    """os.replace with a bounded retry: on Windows a scanner or indexer may briefly hold a file (m7_runtime.replace_with_retry)."""
    import time

    deadline = time.monotonic() + timeout
    delay = 0.005
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.2)


def rmtree_retry(path: Any, timeout: float = 15.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while True:
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def _maybe_crash(crash_at: Optional[str], step: str) -> None:
    if crash_at == step:
        raise SimulatedCrash(step)


def load_latest_verified(root: Path) -> Tuple[Optional[Path], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """The directory (archive, archive.tmp or archive.prev) with a verifying manifest and the highest checkpoint_seq."""
    root = Path(root)
    run = root.parent
    found, report = [], []
    for d in (root, run / "archive.tmp", run / "archive.prev"):
        if not d.is_dir():
            report.append({"dir": d.name, "state": "absent"})
            continue
        problems = verify_manifest(d)
        if problems:
            report.append({"dir": d.name, "state": "unverified", "problems": problems[:3]})
            continue
        meta = json.loads((d / "archive_meta.json").read_text(encoding="utf-8"))
        found.append((int(meta.get("checkpoint_seq", -1)), d, meta))
        report.append({"dir": d.name, "state": "verified", "checkpoint_seq": meta.get("checkpoint_seq")})
    if not found:
        return None, None, report
    found.sort(key=lambda t: t[0])
    return found[-1][1], found[-1][2], report


# -- the ledger audit ----------------------------------------------------------------------------------------------------------


def rebuild(saved: Archive) -> Archive:
    """Replay the ordered ledger of `saved` over its stored bursts: every selection is re-derived and every insert, replace
    and keep decision is re-checked against the rules. Zero native ticks."""
    if not saved.cells:
        raise ArchiveError("nothing to rebuild")
    out = Archive(saved.archive_id)
    c0 = saved.cells[0]
    out.init_cell0(c0.key, c0.end, c0.end_digest, c0.chain)
    c0r = out.cells[0]
    c0r.first_cum = c0.first_cum
    bursts = {b.id: b for b in saved.bursts}
    for ev in saved.events:
        kind = ev["ev"]
        if kind == "dispatch":
            chosen = out.select(ev["it"])
            if chosen.id != ev["cell"]:
                raise ArchiveError(f"iteration {ev['it']}: the rebuilt selection is cell {chosen.id}, the ledger says {ev['cell']}")
            out.apply_dispatch(ev["it"], ev["cell"], ev["worker"])
        elif kind == "fail":
            out.note_failure(ev["it"], ev["why"])
        elif kind == "ingest":
            if ev["burst"] == -1:
                out._pending.pop(ev["it"], None)
                out.events.append(dict(ev))
                continue
            _apply_stored_burst(out, bursts[ev["burst"]])
        else:
            raise ArchiveError(f"unknown ledger event {ev}")
    return out


def _apply_stored_burst(out: Archive, sb: Burst) -> None:
    start = out.cells[sb.start_cell]
    pend = out._pending.pop(sb.iteration, None)
    if pend is None or pend != (sb.start_cell, tuple(sb.start_rep), sb.start_L):
        raise ArchiveError(f"burst {sb.id}: the pinned start representative {tuple(sb.start_rep)} (L {sb.start_L}) differs from "
                           f"the dispatched {pend}")
    if sb.id != len(out.bursts):
        raise ArchiveError(f"burst {sb.id} out of order")
    burst = Burst(id=sb.id, start_cell=sb.start_cell, start_rep=tuple(sb.start_rep), start_L=sb.start_L, words=sb.words,
                  end_reason=sb.end_reason, iteration=sb.iteration, session=sb.session, worker=sb.worker, ticks=sb.ticks,
                  fall_tick=sb.fall_tick, cum_before=sb.cum_before)
    wins = {int(w["j"]): w for w in sb.wins}
    seen_ids: set = set()
    visited: List[int] = []
    new_ids: List[int] = []
    for j, cid, action in sb.reaches:
        w = wins.get(j)
        if action in (ACTION_NEW, ACTION_REPLACE):
            if w is None or int(w["cell"]) != cid or int(w["a"]) != action:
                raise ArchiveError(f"burst {sb.id}: reach at {j} has no matching win record")
            key = (int(w["key"][0]), int(w["key"][1]), str(w["key"][2]), int(w["key"][3]), int(w["key"][4]))
        else:
            key = out.cells[cid].key
        doomed = sb.fall_tick is not None and sb.fall_tick - j <= DOOM_WINDOW
        got, c = out.decide(key, j, doomed)
        if got != action:
            raise ArchiveError(f"burst {sb.id}: reach at {j}: the ledger says action {action}, the rules say {got}")
        if action == ACTION_NEW:
            if cid != len(out.cells):
                raise ArchiveError(f"burst {sb.id}: new cell id {cid} is not the next id {len(out.cells)}")
            c = Cell(id=cid, key=key, level=mcell.level_of_mask(key[3]), L=j, burst=burst.id, offset=j - burst.start_L,
                     parent=start.id, end=tuple(w["end"]), end_digest=bytes.fromhex(w["ed"]), chain=bytes.fromhex(w["ch"]),
                     doomed=doomed, terminal=bool(w["terminal"]), first_iter=sb.iteration, last_iter=sb.iteration,
                     first_cum=burst.cum_before + j)
            out._add(c)
            new_ids.append(cid)
            burst.wins.append(dict(w))
        elif action == ACTION_REPLACE:
            assert c is not None
            out._replace(c, j, burst, start, key, w["end"], bytes.fromhex(w["ed"]), bytes.fromhex(w["ch"]), doomed,
                         bool(w["terminal"]), sb.iteration)
            burst.wins.append(dict(w))
        burst.reaches.append([j, cid, action])
        if cid not in seen_ids:
            seen_ids.add(cid)
            visited.append(cid)
    out.bursts.append(burst)
    for cid in visited:
        c = out.cells[cid]
        c.seen += 1
        c.last_iter = sb.iteration
    start.produced += len(new_ids)
    out._version += 1
    out.events.append({"ev": "ingest", "it": sb.iteration, "burst": burst.id, "cum": burst.cum_before, "ticks": burst.ticks})


def audit(saved: Archive) -> Dict[str, Any]:
    """The close audit (section 8.3): the ledger rebuilds the archive exactly; every prefix reconstructs to its stored L; every
    cell's lineage reaches cell 0."""
    problems: List[str] = []
    try:
        rebuilt = rebuild(saved)
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
        if saved.events != rebuilt.events:
            problems.append("the rebuilt ledger differs from the saved one")
        if saved.diag != rebuilt.diag:
            problems.append("the rebuilt velocity-reversal reading differs from the saved one")
    except ArchiveError as exc:
        problems.append(f"rebuild failed: {exc}")
    lengths_ok = 0
    for c in saved.cells:
        try:
            saved.cell_words(c)
            lengths_ok += 1
        except ArchiveError as exc:
            problems.append(f"cell {c.id}: {exc}")
            if len(problems) > 20:
                break
    return {"ok": not problems, "problems": problems[:20], "cells": len(saved.cells), "bursts": len(saved.bursts),
            "events": len(saved.events), "prefixes_reconstructed": lengths_ok}


# -- coverage-only set (arm C) -----------------------------------------------------------------------------------------------


class CoverageSet:
    """Arm C records cells for coverage only: key -> (first cumulative tick, first tick in its episode). Never selected."""

    def __init__(self) -> None:
        self.keys: Dict[Key, Tuple[int, int]] = {}

    def visit(self, key: Key, cum: int, tick: int) -> bool:
        if key in self.keys:
            return False
        self.keys[key] = (int(cum), int(tick))
        return True

    def stats(self, upto: Optional[int] = None) -> Dict[str, Any]:
        ks = [k for k, (c, _t) in self.keys.items() if upto is None or c <= upto]
        return {"cells": len(ks), "masks": len({k[3] for k in ks}), "bins": len({(k[0], k[1]) for k in ks}),
                "resource": {r: sum(1 for k in ks if k[2] == r) for r in mcell.RESOURCE_CLASSES}}

    def level_first_reach(self, upto: Optional[int] = None) -> Dict[int, Dict[str, int]]:
        out: Dict[int, Dict[str, int]] = {}
        for k, (c, t) in self.keys.items():
            if upto is not None and c > upto:
                continue
            lv = mcell.level_of_mask(k[3])
            d = out.get(lv)
            if d is None or c < d["cum"]:
                out[lv] = {"cum": c, "tick": t}
        return out
