"""M8-rd2: the selection `m8_rd_select_v2` and the archive that continues the rd1 archive under it (pure, standard library only).

Design: docs/rl_m8_rd_continuation_proposal_2026-10-02.md section 2 (frozen), as decided in docs/rl_m8_rd2_decisions_2026-10-02.md.

`Archive2` extends `m8_rd_archive.Archive` without changing it. It has two modes:

    mode 1  the rd1 rules (`m8_rd_select_v1`, replacement by the 60-tick doom flag): used for the part of the ledger that
            rd1 wrote, so that part of the ledger rebuilds exactly as rd1 audited it
    mode 2  `m8_rd_select_v2`, entered by one `session` event in the ledger (`begin_v2`)

Selection v2 separates FEASIBILITY (an exclusion from eligibility, read only from native facts) from PREFERENCE (weights that
never read a position):

    E1  resource class is not X                           E4  not doomed under v1 (the stored 60-tick flag, never rewritten)
    E2  the reach did not end the episode (not terminal)  E5  not descent-doomed (the burst tree, below)
    E3  L <= 3,480                                        E6  not bound-unrecoverable (the rise bound, below)
    X1  a cell with exactly ONE live target is exempt from E4-E6.     Cell 0 is always eligible.

    level   draw a level with weight 1 / (1 + top - level) over the levels that have eligible cells
    cell    w = (1/sqrt(1+chosen) + 1/sqrt(1+seen)) * 900 / (900 + L - L_min(level)) * w_res,   w_res = 1, 1, 1/2, 1/4 for G, A2, A1, A0

Descent doom (E5). A reach (b, o) of an airborne cell is doomed iff no observed continuation of its trajectory reached a grounded
tick AND at least one ended in a native fall. Continuations are the rest of burst b after o and, recursively, every burst whose
pinned start representative is (b, o') with o' >= o. A later landing clears the doom. "Grounded" evidence of a burst is its
grounded REACHES (first visits of a G key within the burst) for every burst, rd1's and rd2's alike; the exact ground runs the rd2
worker records are diagnostics and never read here (decision 5).

Recovery bound (E6). An airborne cell is ineligible iff y + R + 300 < Y_floor_min, R = the character's maximal rise from its
resource class (an upper bound). Y_floor_min is read from the native line table.

Nothing here reads a position, a surface, a target location or a direction in a PREFERENCE; the bound reads only the lowest floor
of the stage and the cell's own height.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import m8_rd_archive as march
import m8_rd_cells as mcell
import m8_rd_explore as mx

SELECT2_CONTRACT = "m8_rd_select_v2"
ARCHIVE_SCHEMA_V2 = "m8_rd_archive_v2"
READABLE_SCHEMAS = (march.ARCHIVE_SCHEMA, ARCHIVE_SCHEMA_V2)
SESSION_NAME = "rd2"
DRAW_SUFFIX = "_v2"                              # the v2-specific draw key: m8_rd|<archive id>_v2|select|<iteration> (decision 9)
W_RES = {mcell.RES_GROUNDED: 1.0, mcell.RES_A2: 1.0, mcell.RES_A1: 0.5, mcell.RES_A0: 0.25, mcell.RES_X: 0.0}   # X is never eligible
AIRBORNE = (mcell.RES_A2, mcell.RES_A1, mcell.RES_A0)

# Mario's rise bound (proposal section 2.2). Every value is an upper bound derived from decomp attribute and motion data and from
# agent flights, never from the TAS or a recording.
GRAVITY = 2.4                                    # decomp/src/relocData/203_MarioMain.c
RISE_AERIAL_JUMP = 1171.8                        # sum over k = 0..30 of (73.8 - 2.4 k), v0 = (80 * 0.7 + 26) * 0.9
RISE_UPB = 1361.3                                # fixed animation-driven rise (M7p agent flights)
RISE_TORNADO = 43 * 40 + 40 * 40 / (2 * GRAVITY) + 20     # 43-tick window at the 40 / tick cap + ballistic tail = 2,073.33
BOUND_MARGIN = 300.0
UPB_STATUS_CLASS = "special_hi"                  # status ids 225 / 226 for Mario


class Select2Error(RuntimeError):
    """A violated v2 archive invariant (never silently tolerated)."""


# -- the contract ----------------------------------------------------------------------------------------------------------------


def y_floor_min() -> float:
    """The lowest vertex of every floor-type line of the native table at tick 0; the moving platform group counts at its lowest
    recorded position (rl/m7g_spatial.EXPECTED_LINES, the table the pin digest covers)."""
    import m7g_spatial as sp

    lows = []
    for _lid, typ, group, _flags, verts in sp.EXPECTED_LINES:
        if typ != sp.LINE_FLOOR:
            continue
        base = sp.PLATFORM_TRANSLATE_Y_RANGE[0] if group == sp.PLATFORM_GROUP else 0.0
        lows.append(min(float(v[1]) for v in verts) + base)
    return min(lows)


def select2_contract_digest(status_table_sha256: str, lines_sha256: str, floor_min: Optional[float] = None) -> str:
    d = {"contract": SELECT2_CONTRACT,
         "eligibility": ["E1 resource class != X", "E2 the representative did not end the episode at L", f"E3 L <= {march.MAX_ELIGIBLE_L}",
                         "E4 not doomed under v1 (the stored 60-tick flag)", "E5 not descent-doomed (burst tree)",
                         "E6 not bound-unrecoverable", "X1 exactly one live target: exempt from E4-E6", "cell 0 always eligible"],
         "level": "weight 1 / (1 + top - level) over the levels that have eligible cells",
         "cell_weight": "(1/sqrt(1+chosen) + 1/sqrt(1+seen)) * 900 / (900 + L - L_min(level over eligible cells)) * w_res",
         "w_res": W_RES, "length_scale": march.LENGTH_SCALE, "doom_window": march.DOOM_WINDOW,
         "descent_doom": "airborne reach (b, o) doomed iff no continuation reached a grounded REACH and a continuation ended in a native "
                         "fall; continuations = the rest of burst b after o and, recursively, every burst whose pinned start "
                         "representative is (b, o') with o' >= o; a later landing clears the doom; grounded evidence = grounded "
                         "reaches for every burst",
         "bound": {"rule": "y + R + margin < Y_floor_min", "margin": BOUND_MARGIN, "gravity": GRAVITY, "aerial_jump": RISE_AERIAL_JUMP,
                   "upb": RISE_UPB, "tornado": RISE_TORNADO, "ballistic": "max(v,0)^2/(2g) + max(v,0)",
                   "classes": {"A2": "B + T + J + U", "A1": "B + T + U", "A0 special_hi": "B + U", "A0 helpless": "B"},
                   "tornado_unspent_assumed": True, "y_floor_min": y_floor_min() if floor_min is None else float(floor_min),
                   "lines_sha256": lines_sha256},
         "replacement": "doom := (E4 or E5 or E6) and not X1, evaluated for the incumbent at the time of the reach and for the new reach "
                        "from its own burst (E5) and its own end record (E6); a non-doomed reach beats a doomed one, then the "
                        "strictly shorter L; ties keep the incumbent",
         "draws": f"two uniforms from sha256(m8_rd|<archive id>{DRAW_SUFFIX}|select|<iteration>), cells in id order; the explorer draws "
                  f"use the same id in m8_rd|<archive id>{DRAW_SUFFIX}|explore|<iteration>|<decision index>",
         "status_table_sha256": status_table_sha256, "reads_position_in_preference": False}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- the rise bound ---------------------------------------------------------------------------------------------------------------


def ballistic_rise(vy: float) -> float:
    v = max(float(vy), 0.0)
    return v * v / (2 * GRAVITY) + v


def rise_bound(res: str, status_class: str, vy: float) -> Optional[float]:
    """The maximal further rise from an airborne state (None for G / X)."""
    hb = ballistic_rise(vy)
    if res == mcell.RES_A2:
        return hb + RISE_TORNADO + RISE_AERIAL_JUMP + RISE_UPB
    if res == mcell.RES_A1:
        return hb + RISE_TORNADO + RISE_UPB
    if res == mcell.RES_A0:
        return hb + (RISE_UPB if status_class == UPB_STATUS_CLASS else 0.0)
    return None


def bound_unrecoverable(res: str, status_class: str, y: float, vy: float, floor_min: float) -> bool:
    r = rise_bound(res, status_class, vy)
    return r is not None and float(y) + r + BOUND_MARGIN < floor_min


# -- the burst tree (descent doom) -------------------------------------------------------------------------------------------------


class DescentTree:
    """Per burst: R (a reach at offset o recovers iff o < R) and F (a fatal continuation exists for offsets o <= F, -1 for none).
    A reach is descent-doomed iff R <= o <= F. Children of a burst are the bursts whose pinned start representative lies in it;
    a child always has a larger id. Maintained incrementally; `reference` recomputes everything from the stored facts."""

    def __init__(self) -> None:
        self.length: List[int] = []
        self.fell: List[bool] = []
        self.last_g: List[int] = []
        self.parent: List[int] = []
        self.par_off: List[int] = []
        self.children: List[List[int]] = []
        self.R: List[int] = []
        self.F: List[int] = []

    def __len__(self) -> int:
        return len(self.length)

    def _eval(self, b: int) -> Tuple[int, int]:
        r = self.last_g[b]
        f = self.length[b] if self.fell[b] else -1
        for c in self.children[b]:
            if self.R[c] >= 1:
                r = max(r, self.par_off[c] + 1)
            elif self.F[c] >= 0:                     # R[c] == 0 and fatal evidence at offset 0: the child's start is doomed
                f = max(f, self.par_off[c])
        return max(r, 0), f

    def add(self, bid: int, length: int, fell: bool, last_g: int, parent: int, par_off: int) -> List[int]:
        """Register burst `bid` (the next id). Returns the bursts whose (R, F) changed, the new burst included."""
        if bid != len(self.length):
            raise Select2Error(f"burst {bid} out of order (next is {len(self.length)})")
        if parent >= bid:
            raise Select2Error(f"burst {bid} starts from a later burst {parent}")
        self.length.append(int(length))
        self.fell.append(bool(fell))
        self.last_g.append(int(last_g))
        self.parent.append(int(parent))
        self.par_off.append(int(par_off))
        self.children.append([])
        self.R.append(0)
        self.F.append(-1)
        self.R[bid], self.F[bid] = self._eval(bid)
        changed = [bid]
        if parent >= 0:
            self.children[parent].append(bid)
            cur = parent
            while cur >= 0:
                old = (self.R[cur], self.F[cur])
                new = self._eval(cur)
                if new == old:
                    break
                self.R[cur], self.F[cur] = new
                changed.append(cur)
                cur = self.parent[cur]
        return changed

    def doomed(self, b: int, o: int) -> bool:
        return b >= 0 and self.R[b] <= o <= self.F[b]

    @staticmethod
    def reference(length: Sequence[int], fell: Sequence[bool], last_g: Sequence[int], parent: Sequence[int],
                  par_off: Sequence[int]) -> Tuple[List[int], List[int]]:
        """The definition, evaluated bottom-up over a finished tree (the scratch analysis of the proposal, in plain loops)."""
        n = len(length)
        kids: List[List[int]] = [[] for _ in range(n)]
        for b in range(n):
            if parent[b] >= 0:
                kids[parent[b]].append(b)
        R = [0] * n
        F = [-1] * n
        for b in range(n - 1, -1, -1):
            r = last_g[b]
            f = length[b] if fell[b] else -1
            for c in kids[b]:
                if R[c] >= 1:
                    r = max(r, par_off[c] + 1)
                elif R[c] == 0 and F[c] >= 0:
                    f = max(f, par_off[c])
            R[b], F[b] = max(r, 0), f
        return R, F


# -- bursts -----------------------------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Burst2(march.Burst):
    """A burst with the two rd2 diagnostic fields (decision 5): `ground_runs` = [[first tick, last tick]] of the exact grounded live
    runs inside the burst, `res_transitions` = [[tick, from, to, x, y]] of every resource-class change. None for an rd1 burst (its
    index row is then byte-identical to rd1's). Never read by the selection."""

    ground_runs: Optional[List[List[int]]] = None
    res_transitions: Optional[List[List[Any]]] = None

    def to_json(self, bin_offset: int) -> Dict[str, Any]:
        d = march.Burst.to_json(self, bin_offset)
        if self.ground_runs is not None:
            d["ground_runs"] = self.ground_runs
            d["res_transitions"] = self.res_transitions if self.res_transitions is not None else []
        return d


def _kkey(k: Sequence[Any]) -> march.Key:
    return (int(k[0]), int(k[1]), str(k[2]), int(k[3]), int(k[4]))


# -- the archive ------------------------------------------------------------------------------------------------------------------


class Archive2(march.Archive):
    def __init__(self, archive_id: str, *, clf: Optional[mcell.Classifier] = None, floor_min: Optional[float] = None):
        super().__init__(archive_id)
        self.draw_id = str(archive_id) + DRAW_SUFFIX
        self.mode = 1
        self.first_iteration: Optional[int] = None
        self.tree = DescentTree()
        self.rep_cells: Dict[int, Set[int]] = {}
        self.desc: List[bool] = []                  # E5 per cell id (derived)
        self.bound: List[bool] = []                 # E6 per cell id (derived)
        self.clf = clf if clf is not None else mcell.Classifier()
        self.floor_min = float(y_floor_min() if floor_min is None else floor_min)
        # reported, never deciding (D8)
        self.diag2: Dict[str, Any] = {"revivals": 0, "newly_descent_doomed": 0, "doomed_incumbent_replacements": 0,
                                      "bound_violations": []}

    # -- derived flags ---------------------------------------------------------------------------------------------------------

    def _end_bound(self, res: str, end: Sequence[Any]) -> bool:
        if res not in AIRBORNE:
            return False
        sc = self.clf.name(int(end[mcell.OBS_INDEX["fighter_status_id"]]))
        return bound_unrecoverable(res, sc, float(end[mcell.I_Y]), float(end[mcell.OBS_INDEX["air_velocity_y"]]), self.floor_min)

    def _add(self, c: march.Cell) -> None:
        super()._add(c)
        while len(self.desc) <= c.id:
            self.desc.append(False)
            self.bound.append(False)
        self.bound[c.id] = self._end_bound(c.key[2], c.end)
        if c.burst >= 0:
            self.rep_cells.setdefault(c.burst, set()).add(c.id)

    def _replace(self, c: march.Cell, j: int, burst: march.Burst, start: march.Cell, key: march.Key, end: Sequence[Any], ed: bytes,
                 ch: bytes, doomed: bool, terminal: bool, it: int) -> None:
        if c.burst >= 0:
            self.rep_cells.get(c.burst, set()).discard(c.id)
        super()._replace(c, j, burst, start, key, end, ed, ch, doomed, terminal, it)
        self.rep_cells.setdefault(c.burst, set()).add(c.id)
        self.bound[c.id] = self._end_bound(c.key[2], c.end)

    def _set_desc(self, cid: int) -> None:
        c = self.cells[cid]
        new = c.key[2] in AIRBORNE and c.burst >= 0 and self.tree.doomed(c.burst, c.offset)
        old = self.desc[cid]
        if new != old:
            self.desc[cid] = new
            if self.mode == 2:
                self.diag2["revivals" if old else "newly_descent_doomed"] += 1

    @staticmethod
    def _x1(c_or_key: Any) -> bool:
        mask = c_or_key.key[3] if hasattr(c_or_key, "key") else c_or_key[3]
        return mcell.popcount(mask) == 1

    def doom_v2(self, c: march.Cell) -> bool:
        """doom := (E4 or E5 or E6) and not X1 (the exclusion the replacement rule and eligibility share)."""
        if self._x1(c):
            return False
        return bool(c.doomed or self.desc[c.id] or self.bound[c.id])

    # -- eligibility and selection ------------------------------------------------------------------------------------------------

    def eligible(self, c: march.Cell) -> bool:                       # type: ignore[override]
        if c.id == 0:
            return True
        if self.mode == 1:
            return march.Archive.eligible(c)
        if c.key[2] == mcell.RES_X or c.terminal or c.L > march.MAX_ELIGIBLE_L:
            return False
        return not self.doom_v2(c)

    def _level_weights(self, order: Sequence[int], top: int) -> List[float]:
        return [1.0 / (1.0 + top - lv) for lv in order]

    def cell_weights(self, cells: Sequence[march.Cell]) -> List[float]:
        lmin = min(c.L for c in cells)
        return [(1.0 / math.sqrt(1 + c.chosen) + 1.0 / math.sqrt(1 + c.seen)) * (march.LENGTH_SCALE / (march.LENGTH_SCALE + c.L - lmin))
                * W_RES[c.key[2]] for c in cells]

    def select(self, iteration: int) -> march.Cell:
        if self.mode == 1:
            return super().select(iteration)
        levels = self.eligible_levels()
        if not levels:
            raise Select2Error("no eligible cell")
        top = max(levels)
        u1, u2 = mx.uniforms(mx.select_key(self.draw_id, iteration))
        order = sorted(levels)
        wl = self._level_weights(order, top)
        r = u1 * sum(wl)
        acc = 0.0
        level = order[-1]
        for lv, w in zip(order, wl):
            acc += w
            if r < acc:
                level = lv
                break
        cells = levels[level]
        ws = self.cell_weights(cells)
        r = u2 * sum(ws)
        acc = 0.0
        for c, w in zip(cells, ws):
            acc += w
            if r < acc:
                return c
        return cells[-1]

    def probabilities(self) -> Dict[int, float]:
        """The analytic selection probability of every eligible cell under the current mode (tests and the reports)."""
        levels = self.eligible_levels()
        out: Dict[int, float] = {}
        if not levels:
            return out
        if self.mode == 1:
            top = max(levels)
            order = sorted(levels)
            wl = [2.0 ** -(top - lv) for lv in order]
            for lv, a in zip(order, wl):
                cells = levels[lv]
                lmin = min(c.L for c in cells)
                ws = [(1.0 / math.sqrt(1 + c.chosen) + 1.0 / math.sqrt(1 + c.seen)) * (march.LENGTH_SCALE / (march.LENGTH_SCALE + c.L - lmin))
                      for c in cells]
                for c, w in zip(cells, ws):
                    out[c.id] = a / sum(wl) * w / sum(ws)
            return out
        top = max(levels)
        order = sorted(levels)
        wl = self._level_weights(order, top)
        tot = sum(wl)
        for lv, a in zip(order, wl):
            cells = levels[lv]
            ws = self.cell_weights(cells)
            s = sum(ws)
            for c, w in zip(cells, ws):
                out[c.id] = a / tot * w / s
        return out

    # -- the session switch ----------------------------------------------------------------------------------------------------

    def begin_v2(self, first_iteration: int, lines_sha256: str) -> Dict[str, Any]:
        """Enter mode 2: one `session` event in the ledger (the digest covers every rule, the status-class table and the pinned
        line table). The dispatch iterations of rd1 are never reused."""
        if self.mode != 1:
            raise Select2Error("already in mode 2")
        if self._pending:
            raise Select2Error(f"{len(self._pending)} dispatched iterations are still pending")
        prior = [e["it"] for e in self.events if e["ev"] == "dispatch"]
        if prior and int(first_iteration) <= max(prior):
            raise Select2Error(f"first iteration {first_iteration} would reuse iteration {max(prior)}")
        ev = {"ev": "session", "name": SESSION_NAME, "select": SELECT2_CONTRACT,
              "digest": select2_contract_digest(self.clf.table_sha256, lines_sha256, self.floor_min), "first_iteration": int(first_iteration)}
        self.events.append(ev)
        self.mode = 2
        self.first_iteration = int(first_iteration)
        self._version += 1
        return ev

    # -- ingestion --------------------------------------------------------------------------------------------------------------

    def _doom_new(self, key: march.Key, e4: bool, o: int, own_r: int, own_f: int, e6: bool) -> bool:
        """The new reach's doom under v2: E4 from the burst's fall window, E5 from its OWN burst (a reach whose burst ended by length
        is pending, so it is not doomed), E6 from its own end record, with the X1 exemption."""
        if mcell.popcount(key[3]) == 1:
            return False
        e5 = key[2] in AIRBORNE and own_r <= o <= own_f
        return bool(e4 or e5 or e6)

    def _decide_v2(self, key: march.Key, new_L: int, new_doom: bool) -> Tuple[int, Optional[march.Cell]]:
        cid = self.by_key.get(key)
        if cid is None:
            return march.ACTION_NEW, None
        c = self.cells[cid]
        if march._better(self.doom_v2(c), c.L, new_doom, new_L):
            if self.doom_v2(c) and not new_doom:
                self.diag2["doomed_incumbent_replacements"] += 1
            return march.ACTION_REPLACE, c
        return march.ACTION_KEEP, c

    def ingest(self, res: Mapping[str, Any]) -> Dict[str, Any]:
        """Insert one finished job. Same inputs as the rd1 archive's `ingest`, plus the optional `ground_runs` and `res_transitions`
        of an `iterate2` result (stored, never read by the selection)."""
        it = int(res["iteration"])
        start = self.cells[int(res["cell"])]
        words = bytes(res["words"])
        start_L = int(res["L"])
        pend = self._pending.pop(it, None)
        replayed = (int(res["rep"][0]), int(res["rep"][1]))
        if pend is not None:
            if pend != (start.id, replayed, start_L):
                raise march.ArchiveError(f"iteration {it}: the result is for (cell {start.id}, rep {replayed}, L {start_L}) but "
                                         f"{pend} was dispatched")
        elif len(self.rep_words(*replayed)) != start_L:
            raise march.ArchiveError(f"iteration {it}: the replayed representative {replayed} has no {start_L}-word trajectory")
        if not words:
            self.events.append({"ev": "ingest", "it": it, "burst": -1, "cum": int(res["cum_before"]), "ticks": int(res["ticks"])})
            return {"burst": -1, "new": 0, "replaced": 0, "kept": 0, "visited": 0, "new_ids": []}
        fall_tick = start_L + len(words) if res["end_reason"] == "fall" else None
        gr = res.get("ground_runs") if self.mode == 2 else None
        burst = Burst2(id=len(self.bursts), start_cell=start.id, start_rep=replayed, start_L=start_L, words=words,
                       end_reason=str(res["end_reason"]), iteration=it, session=str(res.get("session", "")),
                       worker=int(res.get("worker", -1)), ticks=int(res["ticks"]), fall_tick=fall_tick,
                       cum_before=int(res["cum_before"]),
                       ground_runs=[list(map(int, r)) for r in gr] if gr is not None else None,
                       res_transitions=[list(r) for r in (res.get("res_transitions") or [])] if gr is not None else None)
        rows = [(int(j), _kkey(key), tuple(end), bytes(ed), bytes(ch), bool(terminal), None, None)
                for j, key, end, ed, ch, terminal in res["reaches"]]
        return self._ingest_core(burst, start, rows)

    def _ingest_core(self, burst: Burst2, start: march.Cell, rows: Sequence[Tuple[Any, ...]]) -> Dict[str, Any]:
        """The shared insertion logic of a live ingest and of the ledger rebuild. Row = (j, key, end, ed, ch, terminal, e6 bit,
        expected action); `end` is None for a stored KEEP reach (its end record is not stored). Raises ArchiveError when an
        expected action (rebuild) differs from what the rules decide."""
        it = burst.iteration
        start_L = burst.start_L
        n = len(burst.words)
        fall_tick = burst.fall_tick
        own_last_g = max((int(r[0]) - start_L for r in rows if r[1][2] == mcell.RES_GROUNDED), default=-1)
        own_r, own_f = max(own_last_g, 0), (n if fall_tick is not None else -1)
        visited: List[int] = []
        seen_ids: Set[int] = set()
        new_ids: List[int] = []
        touched: Set[int] = set()
        replaced = kept = 0
        last_j = start_L
        for row in rows:
            j, key, end, ed, ch, terminal, e6_bit, want = row
            if not start_L < j <= start_L + n or j <= last_j:
                raise march.ArchiveError(f"iteration {it}: reach tick {j} outside the burst or out of order")
            last_j = j
            e4 = fall_tick is not None and fall_tick - j <= march.DOOM_WINDOW
            e6 = None
            if self.mode == 2:
                if end is not None:
                    e6 = self._end_bound(key[2], end)
                    if e6_bit is not None and bool(e6_bit) != e6:
                        raise march.ArchiveError(f"burst {burst.id}: reach at {j}: the stored bound bit {e6_bit} differs from the end record's {int(e6)}")
                else:
                    if e6_bit is None:
                        raise march.ArchiveError(f"burst {burst.id}: reach at {j}: a v2 burst's kept reach carries no bound bit")
                    e6 = bool(e6_bit)
                new_doom = self._doom_new(key, e4, j - start_L, own_r, own_f, e6)
                action, c = self._decide_v2(key, j, new_doom)
            else:
                action, c = self.decide(key, j, e4)
            if want is not None and action != want:
                raise march.ArchiveError(f"burst {burst.id}: reach at {j}: the ledger says action {want}, the rules say {action}")
            if action == march.ACTION_NEW:
                c = march.Cell(id=len(self.cells), key=key, level=mcell.level_of_mask(key[3]), L=j, burst=burst.id, offset=j - start_L,
                               parent=start.id, end=tuple(end), end_digest=bytes(ed), chain=bytes(ch), doomed=e4, terminal=bool(terminal),
                               first_iter=it, last_iter=it, first_cum=burst.cum_before + j)
                self._add(c)
                new_ids.append(c.id)
                burst.wins.append(dict(j=j, key=list(key), end=list(end), ed=bytes(ed).hex(), ch=bytes(ch).hex(), doomed=int(e4),
                                       terminal=int(bool(terminal)), cell=c.id, a=action))
                touched.add(c.id)
            elif action == march.ACTION_REPLACE:
                assert c is not None
                self._replace(c, j, burst, start, key, end, ed, ch, e4, bool(terminal), it)
                replaced += 1
                burst.wins.append(dict(j=j, key=list(key), end=list(end), ed=bytes(ed).hex(), ch=bytes(ch).hex(), doomed=int(e4),
                                       terminal=int(bool(terminal)), cell=c.id, a=action))
                touched.add(c.id)
            else:
                assert c is not None
                kept += 1
            if self.mode == 2:
                burst.reaches.append([j, c.id, action, int(bool(e6))])
            else:
                burst.reaches.append([j, c.id, action])
            if c.id not in seen_ids:
                seen_ids.add(c.id)
                visited.append(c.id)
        self.bursts.append(burst)
        changed = self.tree.add(burst.id, n, fall_tick is not None, own_last_g, burst.start_rep[0], burst.start_rep[1])
        refresh = set(touched)
        for b in changed:
            refresh |= self.rep_cells.get(b, set())
        for cid in sorted(refresh):
            self._set_desc(cid)
        if self.mode == 2 and burst.ground_runs is not None:
            self._check_bound(burst, rows)
        for cid in visited:
            cc = self.cells[cid]
            cc.seen += 1
            cc.last_iter = it
        start.produced += len(new_ids)
        self._version += 1
        self.events.append({"ev": "ingest", "it": it, "burst": burst.id, "cum": burst.cum_before, "ticks": burst.ticks})
        return {"burst": burst.id, "new": len(new_ids), "replaced": replaced, "kept": kept, "visited": len(visited), "new_ids": new_ids}

    def _check_bound(self, burst: Burst2, rows: Sequence[Tuple[Any, ...]]) -> None:
        """BOUND_VIOLATION (S5): a reach the bound calls unrecoverable that is followed, in the same burst, by an exact grounded live
        tick. Diagnostic only: it changes no selection."""
        runs = burst.ground_runs or []
        if not runs:
            return
        last_ground = max(int(r[1]) for r in runs)
        for row in rows:
            j, key = int(row[0]), row[1]
            e6 = self._end_bound(key[2], row[2]) if row[2] is not None else bool(row[6])
            if e6 and last_ground > j:
                self.diag2["bound_violations"].append({"burst": burst.id, "iteration": burst.iteration, "reach_tick": j,
                                                       "key": list(key), "last_grounded_tick": last_ground})

    # -- derived state from stored data -----------------------------------------------------------------------------------------

    def rebuild_derived(self) -> None:
        """Recompute the tree, the representative index and both flags from the stored cells and bursts (after a load)."""
        self.tree = DescentTree()
        self.rep_cells = {}
        self.desc = [False] * len(self.cells)
        self.bound = [False] * len(self.cells)
        key_res = [c.key[2] for c in self.cells]
        for b in self.bursts:
            last_g = max((j - b.start_L for j, cid, *_a in b.reaches if key_res[cid] == mcell.RES_GROUNDED), default=-1)
            self.tree.add(b.id, len(b.words), b.end_reason == "fall", last_g, b.start_rep[0], b.start_rep[1])
        saved_mode = self.mode
        self.mode = 1                                  # the derived flags below are state, not events: no counters
        for c in self.cells:
            if c.burst >= 0:
                self.rep_cells.setdefault(c.burst, set()).add(c.id)
            self.bound[c.id] = self._end_bound(c.key[2], c.end)
            self._set_desc(c.id)
        self.mode = saved_mode
        self._version += 1

    def reference_flags(self) -> Tuple[List[bool], List[bool]]:
        """E5 and E6 of every cell from first principles (plain loops over the stored bursts), independent of the incremental tree."""
        nb = len(self.bursts)
        key_res = [c.key[2] for c in self.cells]
        length = [len(b.words) for b in self.bursts]
        fell = [b.end_reason == "fall" for b in self.bursts]
        last_g = [max((j - b.start_L for j, cid, *_a in b.reaches if key_res[cid] == mcell.RES_GROUNDED), default=-1) for b in self.bursts]
        parent = [b.start_rep[0] for b in self.bursts]
        par_off = [b.start_rep[1] for b in self.bursts]
        R, F = DescentTree.reference(length, fell, last_g, parent, par_off)
        desc = [bool(c.key[2] in AIRBORNE and c.burst >= 0 and R[c.burst] <= c.offset <= F[c.burst]) for c in self.cells]
        bound = [self._end_bound(c.key[2], c.end) for c in self.cells]
        assert len(R) == nb
        return desc, bound

    # -- persistence -------------------------------------------------------------------------------------------------------------

    def write_files(self, directory: Path, meta: Mapping[str, Any]) -> Dict[str, str]:
        directory = Path(directory)
        super().write_files(directory, meta)
        sess = [e for e in self.events if e["ev"] == "session"]
        full = dict(meta, schema=ARCHIVE_SCHEMA_V2, archive_id=self.archive_id, cells=len(self.cells), bursts=len(self.bursts),
                    events=len(self.events), select_contract=march.SELECT_CONTRACT, select_digest=march.select_contract_digest(),
                    select2_contract=SELECT2_CONTRACT, select2_digest=sess[-1]["digest"] if sess else None, mode=self.mode,
                    first_iteration=self.first_iteration, draw_id=self.draw_id, floor_min=self.floor_min, diag=self.diag, diag2=self.diag2)
        march._write_text(directory / "archive_meta.json", json.dumps(full, indent=1, sort_keys=True) + "\n")
        return march.write_manifest(directory)

    @staticmethod
    def read_dir(directory: Path, *, clf: Optional[mcell.Classifier] = None, floor_min: Optional[float] = None
                 ) -> Tuple["Archive2", Dict[str, Any]]:
        """Load an archive directory (rd1's schema or this one) after verifying its manifest; the derived state is rebuilt."""
        directory = Path(directory)
        bad = march.verify_manifest(directory)
        if bad:
            raise march.ArchiveError(f"{directory}: manifest verification failed: {bad[:4]}")
        meta = json.loads((directory / "archive_meta.json").read_text(encoding="utf-8"))
        if meta.get("schema") not in READABLE_SCHEMAS:
            raise march.ArchiveError(f"{directory}: schema {meta.get('schema')!r}")
        a = Archive2(meta["archive_id"], clf=clf, floor_min=floor_min if floor_min is not None else meta.get("floor_min"))
        if meta.get("diag"):
            a.diag = {"velocity_reversals": int(meta["diag"]["velocity_reversals"]),
                      "velocity_reversal_examples": list(meta["diag"]["velocity_reversal_examples"])}
        for line in (directory / "cells.jsonl").read_text(encoding="utf-8").splitlines():
            a.cells.append(march.Cell.from_json(json.loads(line)))
        a.by_key = {c.key: c.id for c in a.cells}
        for c in a.cells:
            a._level_cells.setdefault(c.level, []).append(c)
        blob = (directory / "bursts.bin").read_bytes()
        for line in (directory / "bursts.idx.jsonl").read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            off, n = int(d["bin_off"]), int(d["n"])
            a.bursts.append(Burst2(id=int(d["id"]), start_cell=int(d["start_cell"]), start_rep=(int(d["start_rep"][0]), int(d["start_rep"][1])),
                                   start_L=int(d["start_L"]), words=blob[off:off + n], end_reason=d["end_reason"], iteration=int(d["iteration"]),
                                   session=d["session"], worker=int(d["worker"]), ticks=int(d["ticks"]), fall_tick=d["fall_tick"],
                                   cum_before=int(d["cum_before"]), reaches=[list(r) for r in d["reaches"]], wins=list(d["wins"]),
                                   ground_runs=d.get("ground_runs"), res_transitions=d.get("res_transitions")))
        a.events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        a._version += 1
        sess = [e for e in a.events if e["ev"] == "session"]
        if sess:
            a.mode = 2
            a.first_iteration = int(sess[-1]["first_iteration"])
            if meta.get("diag2"):
                a.diag2 = json.loads(json.dumps(meta["diag2"]))
        a.rebuild_derived()
        return a, meta


# -- the ledger rebuild and audit (both modes) --------------------------------------------------------------------------------------


def _stored_rows(out: Archive2, sb: march.Burst) -> Tuple[List[Tuple[Any, ...]], Dict[int, Mapping[str, Any]]]:
    wins = {int(w["j"]): w for w in sb.wins}
    rows: List[Tuple[Any, ...]] = []
    for r in sb.reaches:
        j, cid, action = int(r[0]), int(r[1]), int(r[2])
        bit = int(r[3]) if len(r) > 3 else None
        if action in (march.ACTION_NEW, march.ACTION_REPLACE):
            w = wins.get(j)
            if w is None or int(w["cell"]) != cid or int(w["a"]) != action:
                raise march.ArchiveError(f"burst {sb.id}: reach at {j} has no matching win record")
            rows.append((j, _kkey(w["key"]), tuple(w["end"]), bytes.fromhex(w["ed"]), bytes.fromhex(w["ch"]), bool(w["terminal"]), bit, action))
        else:
            if cid >= len(out.cells):
                raise march.ArchiveError(f"burst {sb.id}: reach at {j} names cell {cid}, which does not exist yet")
            rows.append((j, out.cells[cid].key, None, b"", b"", False, bit, action))
    return rows, wins


def _apply_stored_burst2(out: Archive2, sb: march.Burst) -> None:
    start = out.cells[sb.start_cell]
    pend = out._pending.pop(sb.iteration, None)
    if pend is None or pend != (sb.start_cell, tuple(sb.start_rep), sb.start_L):
        raise march.ArchiveError(f"burst {sb.id}: the pinned start representative {tuple(sb.start_rep)} (L {sb.start_L}) differs from "
                                 f"the dispatched {pend}")
    if sb.id != len(out.bursts):
        raise march.ArchiveError(f"burst {sb.id} out of order")
    has_new = getattr(sb, "ground_runs", None) is not None
    burst = Burst2(id=sb.id, start_cell=sb.start_cell, start_rep=tuple(sb.start_rep), start_L=sb.start_L, words=sb.words,
                   end_reason=sb.end_reason, iteration=sb.iteration, session=sb.session, worker=sb.worker, ticks=sb.ticks,
                   fall_tick=sb.fall_tick, cum_before=sb.cum_before,
                   ground_runs=[list(r) for r in sb.ground_runs] if has_new else None,
                   res_transitions=[list(r) for r in (sb.res_transitions or [])] if has_new else None)
    rows, _wins = _stored_rows(out, sb)
    out._ingest_core(burst, start, rows)


def rebuild2(saved: Archive2, lines_sha256: str) -> Archive2:
    """Replay the ordered ledger over the stored bursts: the rd1 part under v1, the `session` event, then the rd2 part under v2.
    Every selection is re-derived and every insert / replace / keep decision is re-checked. Zero native ticks."""
    if not saved.cells:
        raise march.ArchiveError("nothing to rebuild")
    out = Archive2(saved.archive_id, clf=saved.clf, floor_min=saved.floor_min)
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
            made = out.begin_v2(int(ev["first_iteration"]), lines_sha256)
            if made != ev:
                raise march.ArchiveError(f"the rebuilt session event {made} differs from the ledger's {ev}")
        elif kind == "ingest":
            if ev["burst"] == -1:
                out._pending.pop(ev["it"], None)
                out.events.append(dict(ev))
                continue
            _apply_stored_burst2(out, bursts[ev["burst"]])
        else:
            raise march.ArchiveError(f"unknown ledger event {ev}")
    return out


def audit2(saved: Archive2, lines_sha256: str) -> Dict[str, Any]:
    """The close audit: the ledger rebuilds the archive exactly (rd1 part under v1, rd2 part under v2); every prefix reconstructs;
    every lineage reaches cell 0; the incremental derived state equals the first-principles recomputation."""
    problems: List[str] = []
    try:
        rebuilt = rebuild2(saved, lines_sha256)
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
    except march.ArchiveError as exc:
        problems.append(f"rebuild failed: {exc}")
    try:
        ref_desc, ref_bound = saved.reference_flags()
        if ref_desc != saved.desc:
            problems.append(f"{sum(x != y for x, y in zip(ref_desc, saved.desc))} descent flags differ from the first-principles recomputation")
        if ref_bound != saved.bound:
            problems.append("the bound flags differ from the first-principles recomputation")
    except (IndexError, KeyError, ValueError) as exc:
        problems.append(f"the first-principles recomputation failed: {type(exc).__name__}: {exc}")
    lengths_ok = 0
    for c in saved.cells:
        try:
            saved.cell_words(c)
            lengths_ok += 1
        except march.ArchiveError as exc:
            problems.append(f"cell {c.id}: {exc}")
            if len(problems) > 20:
                break
    return {"ok": not problems, "problems": problems[:20], "cells": len(saved.cells), "bursts": len(saved.bursts),
            "events": len(saved.events), "prefixes_reconstructed": lengths_ok}


# -- the open overlay ---------------------------------------------------------------------------------------------------------------


def overlay_rows(a: Archive2, desc: Optional[Sequence[bool]] = None, bound: Optional[Sequence[bool]] = None) -> List[Dict[str, Any]]:
    """The v2 flags of every cell (E1-E6, X1) with reason codes. Nothing is stored in the cells; this is derived, recorded at the open
    with a digest, and recomputed at the close. Reason codes: x, terminal, horizon, doom60, descent, bound."""
    desc = a.desc if desc is None else desc
    bound = a.bound if bound is None else bound
    rows = []
    for c in a.cells:
        reasons: List[str] = []
        if c.id != 0:
            if c.key[2] == mcell.RES_X:
                reasons.append("x")
            if c.terminal:
                reasons.append("terminal")
            if c.L > march.MAX_ELIGIBLE_L:
                reasons.append("horizon")
            if mcell.popcount(c.key[3]) != 1:
                if c.doomed:
                    reasons.append("doom60")
                if desc[c.id]:
                    reasons.append("descent")
                if bound[c.id]:
                    reasons.append("bound")
        rows.append({"id": c.id, "eligible": not reasons, "reasons": reasons, "w_res": W_RES[c.key[2]],
                     "x1": bool(c.id != 0 and mcell.popcount(c.key[3]) == 1)})
    return rows


def overlay_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return "".join(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n" for r in rows).encode("utf-8")


def overlay_counts(a: Archive2, rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The figures the proposal reports for the rd2 open (its section 2.4(d)): counted among the cells that are eligible under v1."""
    v1 = [c for c in a.cells if march.Archive.eligible(c)]
    by = {c.id: r for c, r in zip(a.cells, rows)}
    desc_ids = [c.id for c in v1 if "descent" in by[c.id]["reasons"]]
    bound_ids = [c.id for c in v1 if "bound" in by[c.id]["reasons"]]
    union = set(desc_ids) | set(bound_ids)
    left = [c for c in v1 if c.id not in union]

    def region(c: march.Cell) -> str:
        y, x = float(c.end[mcell.I_Y]), float(c.end[mcell.I_X])
        if y < -2850:
            return "below"
        if x > 3600:
            return "beside"
        return "onlow" if y < 0 else "onhigh"

    launch = lambda c: c.key[2] in (mcell.RES_A2, mcell.RES_A1) and float(c.end[mcell.I_Y]) >= 1639.0       # noqa: E731
    cells = {c.id: c for c in a.cells}
    out: Dict[str, Any] = {
        "cells": len(a.cells), "eligible_v1": len(v1), "descent_among_v1_eligible": len(desc_ids),
        "bound_among_v1_eligible": len(bound_ids), "union": len(union), "eligible_v2": len(left),
        "descent_by_region": {k: sum(1 for i in desc_ids if region(cells[i]) == k) for k in ("below", "beside", "onlow", "onhigh")},
        "bound_by_class": {r: sum(1 for i in bound_ids if cells[i].key[2] == r) for r in (mcell.RES_A2, mcell.RES_A1, mcell.RES_A0)},
        "bound_below_floor": sum(1 for i in bound_ids if region(cells[i]) == "below"),
        "descent_a2a1_on_stage_y_ge_0": sum(1 for i in desc_ids if cells[i].key[2] in (mcell.RES_A2, mcell.RES_A1)
                                            and float(cells[i].end[mcell.I_Y]) >= 0 and float(cells[i].end[mcell.I_X]) <= 3600),
        "descent_a2_y_ge_0": sum(1 for i in desc_ids if cells[i].key[2] == mcell.RES_A2 and float(cells[i].end[mcell.I_Y]) >= 0),
        "descent_launch_capable": sum(1 for i in desc_ids if launch(cells[i])),
        "descent_grounded": sum(1 for i in desc_ids if cells[i].key[2] == mcell.RES_GROUNDED),
        "still_eligible": {"launch_capable": sum(1 for c in left if launch(c)),
                           "step_contact": sum(1 for c in left if c.key[2] == mcell.RES_GROUNDED and c.key[4] == 1),
                           "grounded": sum(1 for c in left if c.key[2] == mcell.RES_GROUNDED)},
        "a2a1_on_stage_y_ge_0_v1_eligible": sum(1 for c in v1 if c.key[2] in (mcell.RES_A2, mcell.RES_A1)
                                                and float(c.end[mcell.I_Y]) >= 0 and float(c.end[mcell.I_X]) <= 3600),
        "launch_capable_cells": sum(1 for c in a.cells if launch(c)),
        "step_contact_cells": sum(1 for c in a.cells if c.key[2] == mcell.RES_GROUNDED and c.key[4] == 1),
        "grounded_cells": sum(1 for c in a.cells if c.key[2] == mcell.RES_GROUNDED),
    }
    return out
